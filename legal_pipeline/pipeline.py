from __future__ import annotations
import argparse, json, shutil, time, traceback
from pathlib import Path
from typing import Dict, List
from tqdm import tqdm

from .config import Config
from .extract import extract_document, normalise_text, sha256_text, ExtractedDoc
from .classify import classify_document
from .metadata import extract_metadata
from .dedupe import DedupRecord, deduplicate
from . import ocr_support


def _load_cache(cache_path):
    cache = {}
    if cache_path.exists():
        with cache_path.open() as f:
            for line in f:
                try:
                    d = json.loads(line); cache[d["path"]] = d
                except Exception:
                    continue
    return cache


_EXTRACTED_DOC_FIELDS = {f.name for f in __import__("dataclasses").fields(ExtractedDoc)}


def stage_extract(cfg, pdfs, progress=None):
    cache = _load_cache(cfg.paths.cache_path())
    cfg.paths.cache_path().parent.mkdir(parents=True, exist_ok=True)
    docs, new_lines = [], []
    total = len(pdfs)
    it = pdfs if progress else tqdm(pdfs, desc="Extracting text", unit="pdf")
    for i, p in enumerate(it, start=1):
        if progress: progress("extract", i, total, p.name)
        try:
            key = str(p.resolve())
            stat = p.stat()
            cached = cache.get(key)
            if (cached is not None
                    and cached.get("size_bytes") == stat.st_size
                    and cached.get("mtime_ns") == stat.st_mtime_ns):
                clean = {k: v for k, v in cached.items() if k in _EXTRACTED_DOC_FIELDS}
                docs.append(ExtractedDoc(**clean)); continue
            doc = extract_document(p, cfg.ingestion)
        except Exception as e:
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            doc = ExtractedDoc(
                path=str(p), file_name=p.name, size_bytes=size, page_count=0,
                text="", extraction_method="failed",
                file_sha256=f"__unreadable__:{p}",
                text_sha256=sha256_text(""), is_scanned=False,
                error=f"could not process file: {e}\n{traceback.format_exc(limit=2)}",
            )
        docs.append(doc)
        try:
            mtime_ns = p.stat().st_mtime_ns
        except Exception:
            mtime_ns = None
        cache_line = doc.to_dict()
        cache_line["mtime_ns"] = mtime_ns
        new_lines.append(json.dumps(cache_line))
    if new_lines:
        with cfg.paths.cache_path().open("a") as f:
            f.write("\n".join(new_lines) + "\n")
    return docs


def stage_enrich(cfg, docs, progress=None):
    rows = []
    total = len(docs)
    it = docs if progress else tqdm(docs, desc="Classify + metadata", unit="doc")
    for i, d in enumerate(it):
        if progress: progress("enrich", i + 1, total, d.file_name)
        cls = classify_document(d.text, cfg.classify)
        meta = extract_metadata(d.text)
        rows.append({
            "idx": i, "path": d.path, "file_name": d.file_name,
            "size_bytes": d.size_bytes, "size_kb": round(d.size_bytes / 1024, 1),
            "page_count": d.page_count, "extraction_method": d.extraction_method,
            "is_scanned": d.is_scanned, "file_sha256": d.file_sha256,
            "text_sha256": d.text_sha256, "text_len": len(d.text or ""),
            "extract_error": d.error or "", "doc_type": cls.doc_type,
            "score": cls.score, "confidence": cls.confidence,
            "needs_review": cls.needs_review, "matched_terms": cls.matched_terms,
            **meta.to_dict(), "status": "retained", "is_duplicate": False,
            "duplicate_of": "", "dup_group_id": None, "dup_method": "",
            "similarity": None, "target_folder": "", "consolidated_path": "",
        })
    return rows


def stage_dedupe(cfg, rows, docs, progress=None):
    records = [DedupRecord(
        idx=r["idx"], file_name=r["file_name"], doc_type=r["doc_type"],
        text_norm=normalise_text(docs[r["idx"]].text), file_sha256=r["file_sha256"],
        text_sha256=r["text_sha256"], entity_name=r["entity_name"],
        contract_date=r["contract_date"], description=r["description"],
        extraction_method=r["extraction_method"], size_bytes=r["size_bytes"],
        text_len=r["text_len"]) for r in rows]

    def _dedupe_progress(done, total):
        if progress:
            progress("dedupe", done, max(total, 1), f"{done}/{total} compared")

    deduplicate(records, cfg.dedup, progress=_dedupe_progress if progress else None)
    by_idx = {rec.idx: rec for rec in records}
    for r in rows:
        rec = by_idx[r["idx"]]
        r.update(status=rec.status, is_duplicate=rec.is_duplicate,
                 duplicate_of=rec.duplicate_of, dup_group_id=rec.dup_group_id,
                 dup_method=rec.dup_method, similarity=rec.similarity)
    return rows


def _unique_dest(folder: Path, file_name: str, idx: int) -> Path:
    dest = folder / file_name
    if dest.exists():
        dest = folder / f"{dest.stem}__{idx}{dest.suffix}"
    return dest


def stage_organise(cfg, rows, copy_removed=False, progress=None):
    class_root = cfg.paths.organised_dir()
    consolidated = cfg.paths.consolidated_dir()

    if class_root.exists():
        shutil.rmtree(class_root)
    if consolidated.exists():
        shutil.rmtree(consolidated)
    consolidated.mkdir(parents=True, exist_ok=True)

    total = len(rows)
    for i, r in enumerate(rows, start=1):
        if progress: progress("organise", i, total, r["file_name"])
        if r["is_duplicate"] and not copy_removed:
            r["target_folder"] = "(not copied — duplicate)"
            r["consolidated_path"] = "(not copied — duplicate)"
            continue

        subfolder = class_root / r["doc_type"]
        if r["confidence"] == "LOW" or r["doc_type"] == "Other":
            subfolder = subfolder / "_REVIEW"
        subfolder.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(subfolder, r["file_name"], r["idx"])
        try:
            shutil.copy2(r["path"], dest); r["target_folder"] = str(dest)
        except Exception as e:
            r["target_folder"] = f"(copy failed: {e})"

        cdest = _unique_dest(consolidated, r["file_name"], r["idx"])
        try:
            shutil.copy2(r["path"], cdest); r["consolidated_path"] = str(cdest)
        except Exception as e:
            r["consolidated_path"] = f"(copy failed: {e})"


def stage_tracker(cfg, rows, ocr_note):
    from .tracker import build_tracker
    return build_tracker(rows, cfg.paths.tracker_path(),
                         ocr_note=ocr_note, consolidated_dir=cfg.paths.consolidated_dir())


def run(cfg, copy_files=True, log=print, progress=None):
    t0 = time.time()
    ocr_note = "disabled"
    if cfg.ingestion.enable_ocr:
        status = ocr_support.configure_ocr(); ocr_note = status.summary()
        log(f"[OCR] {ocr_note}")
        if status.ready:
            cfg.ingestion.tesseract_cmd = cfg.ingestion.tesseract_cmd or status.tesseract_path
            cfg.ingestion.poppler_path = cfg.ingestion.poppler_path or status.poppler_path
        if not status.ready:
            log("[OCR] Scanned files will be flagged for review instead of read.")
    else:
        log("[OCR] Disabled by user — scanned files flagged for review.")

    src = cfg.paths.source_dir
    if not src.exists(): raise SystemExit(f"Input folder does not exist: {src}")
    pdfs = sorted(set(sorted(src.rglob("*.pdf")) + sorted(src.rglob("*.PDF"))))
    if not pdfs: raise SystemExit(f"No PDF files found under {src.resolve()}")
    if progress: progress("scan", 1, 1, f"{len(pdfs)} PDFs found")

    log(f"[1/6] Found {len(pdfs)} PDFs under {src}")
    docs = stage_extract(cfg, pdfs, progress=progress)
    n_ocr = sum(1 for d in docs if d.extraction_method == "ocr")
    log(f"[2/6] Extracted text ({sum(1 for d in docs if d.is_scanned)} scanned; {n_ocr} read via OCR)")
    rows = stage_enrich(cfg, docs, progress=progress)
    log("[3/6] Classified + metadata extracted")
    rows = stage_dedupe(cfg, rows, docs, progress=progress)
    retained = sum(1 for r in rows if r["status"] == "retained")
    removed = len(rows) - retained
    log(f"[4/6] Deduplicated: {retained} retained, {removed} removed")

    if copy_files:
        stage_organise(cfg, rows, progress=progress)
        log(f"[5/6] Organised retained files -> {cfg.paths.organised_dir()}")
        log(f"      + Consolidated all {retained} retained files -> {cfg.paths.consolidated_dir()}")
    else:
        for r in rows:
            r["target_folder"] = "(copy skipped)"; r["consolidated_path"] = "(copy skipped)"
        if progress: progress("organise", 1, 1, "(copy skipped)")
        log("[5/6] File copy skipped")

    tracker = stage_tracker(cfg, rows, ocr_note)
    if progress: progress("tracker", 1, 1, str(tracker))
    log(f"[6/6] Tracker written -> {tracker}")

    n_failed = sum(1 for r in rows if r["extraction_method"] == "failed")
    summary = {
        "total": len(rows), "retained": retained, "removed": removed,
        "needs_review": sum(1 for r in rows if r["needs_review"]),
        "scanned": sum(1 for r in rows if r["is_scanned"]),
        "ocr_read": n_ocr, "failed_extraction": n_failed, "ocr_engine": ocr_note,
        "consolidated_dir": str(cfg.paths.consolidated_dir()),
        "tracker": str(tracker), "output_dir": str(cfg.paths.output_dir),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    log("\n=== SUMMARY ===")
    for k, v in summary.items(): log(f"  {k:16}: {v}")
    if progress: progress("done", 1, 1, "")
    return summary


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Legal document migration pipeline")
    ap.add_argument("--source", type=Path); ap.add_argument("--output", type=Path)
    ap.add_argument("--similarity", type=float); ap.add_argument("--no-copy", action="store_true")
    ap.add_argument("--no-ocr", action="store_true")
    return ap.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv); cfg = Config()
    if args.source: cfg.paths.source_dir = args.source
    if args.output: cfg.paths.output_dir = args.output
    if args.similarity is not None: cfg.dedup.near_dup_similarity = args.similarity
    if args.no_ocr: cfg.ingestion.enable_ocr = False
    run(cfg, copy_files=not args.no_copy)


if __name__ == "__main__":
    main()
