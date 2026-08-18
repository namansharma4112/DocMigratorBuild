"""dedupe.py — three-tier deduplication: exact file, exact text, near-duplicate."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, List, Optional
try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False

ProgressFn = Optional[Callable[[int, int], None]]
LogFn = Optional[Callable[[str], None]]
_LARGE_BUCKET_WARNING_THRESHOLD = 3000


@dataclass
class DedupRecord:
    idx: int
    file_name: str
    doc_type: str
    text_norm: str
    file_sha256: str
    text_sha256: str
    entity_name: str
    contract_date: str
    description: str
    extraction_method: str
    size_bytes: int
    text_len: int
    status: str = "retained"
    is_duplicate: bool = False
    duplicate_of: str = ""
    dup_group_id: Optional[int] = None
    dup_method: str = ""
    similarity: Optional[float] = None


def _mark(rec: DedupRecord, anchor: DedupRecord, group_id: int, method: str, sim: float):
    rec.status = "removed"
    rec.is_duplicate = True
    rec.duplicate_of = anchor.file_name
    rec.dup_group_id = group_id
    rec.dup_method = method
    rec.similarity = round(sim, 4)


def _mark_exact(records: List[DedupRecord], key_fn, method: str, group_id_start: int) -> int:
    groups = defaultdict(list)
    for r in records:
        if r.status != "retained":
            continue
        key = key_fn(r)
        if not key:
            continue
        groups[key].append(r)
    gid = group_id_start
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: r.idx)
        anchor = members[0]
        gid += 1
        anchor.dup_group_id = anchor.dup_group_id or gid
        for dup in members[1:]:
            _mark(dup, anchor, gid, method, 1.0)
    return gid


def _involves_ocr(a: DedupRecord, b: DedupRecord) -> bool:
    return a.extraction_method == "ocr" or b.extraction_method == "ocr"


def _fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _entity_compatible(a: DedupRecord, b: DedupRecord, cfg) -> bool:
    ea, eb = (a.entity_name or "").strip().lower(), (b.entity_name or "").strip().lower()
    if not ea or not eb:
        return True
    if ea == eb:
        return True
    if _involves_ocr(a, b):
        return _fuzzy_ratio(ea, eb) >= cfg.entity_fuzzy_threshold
    return False


def _date_compatible(a: DedupRecord, b: DedupRecord) -> bool:
    if a.extraction_method == "ocr" or b.extraction_method == "ocr":
        return True
    da, db = (a.contract_date or "").strip(), (b.contract_date or "").strip()
    if not da or not db:
        return True
    return da == db


def _similarity_threshold_for(a: DedupRecord, b: DedupRecord, cfg) -> float:
    return cfg.near_dup_similarity_ocr if _involves_ocr(a, b) else cfg.near_dup_similarity


def _build_tfidf(texts: List[str]):
    """Return the SPARSE TF-IDF matrix (n_docs x n_features), NOT a dense
    n x n similarity matrix.

    SCALE FIX: the previous implementation materialised the full dense
    cosine_similarity(matrix) — an N x N float64 array. For a single large
    doc_type bucket (e.g. the 'Contracts' catch-all) at 10-15k documents that
    is ~0.8-1.8 GB allocated in one block, a real out-of-memory / stability
    risk on big runs. We instead keep only the cheap sparse TF-IDF matrix and
    compute each document's similarity against the *current anchors* on demand
    (see the loop below). The per-pair cosine values are computed from exactly
    the same TF-IDF vectors, so the numeric results — and therefore every
    dedupe decision — are byte-for-byte identical to the old dense path; only
    the peak memory changes (from O(N^2) to O(N x nnz))."""
    if not _HAS_SKLEARN:
        return None
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
        return vec.fit_transform(texts)
    except Exception:
        return None


def _mark_near_duplicates(records: List[DedupRecord], cfg, group_id_start: int,
                           progress: ProgressFn = None, log: LogFn = None) -> int:
    log = log or (lambda *_: None)
    candidates = [r for r in records
                  if r.status == "retained" and len(r.text_norm or "") >= cfg.min_chars_for_similarity]
    if len(candidates) < 2:
        if progress:
            progress(0, 0)
        return group_id_start
    gid = group_id_start
    if cfg.block_by_type:
        buckets = defaultdict(list)
        for r in candidates:
            buckets[r.doc_type].append(r)
        bucket_list = list(buckets.items())
    else:
        bucket_list = [("(all)", candidates)]
    total = len(candidates)
    done = 0
    for bucket_name, bucket in bucket_list:
        if len(bucket) < 2:
            done += len(bucket)
            if progress:
                progress(done, total)
            continue
        if len(bucket) > _LARGE_BUCKET_WARNING_THRESHOLD:
            log(f"[DEDUPE] Large batch in '{bucket_name}' ({len(bucket)} documents) - "
                f"near-duplicate comparison for this group may take noticeably longer.")
        bucket.sort(key=lambda r: r.idx)
        pos_of = {id(r): i for i, r in enumerate(bucket)}
        tfidf = _build_tfidf([r.text_norm for r in bucket])
        anchor_positions: List[int] = []
        anchors: List[DedupRecord] = []
        for i, rec in enumerate(bucket):
            if rec.status != "retained":
                done += 1
                if progress and (done % 25 == 0 or done == total):
                    progress(done, total)
                continue
            best_anchor, best_sim = None, 0.0
            if anchors:
                if tfidf is not None:
                    # On-demand: cosine of row i vs ONLY the current anchor
                    # rows — identical values to the old dense
                    # sim_matrix[i, anchor_positions], without the N x N array.
                    sims = cosine_similarity(tfidf[i], tfidf[anchor_positions])[0]
                    best_j_local = int(np.argmax(sims))
                    best_sim = float(sims[best_j_local])
                    best_anchor = anchors[best_j_local]
                else:
                    for anchor in anchors:
                        sa = set(rec.text_norm.split())
                        sb = set(anchor.text_norm.split())
                        sim = len(sa & sb) / max(1, len(sa | sb))
                        if sim > best_sim:
                            best_sim, best_anchor = sim, anchor
            if best_anchor is not None:
                threshold = _similarity_threshold_for(rec, best_anchor, cfg)
                if (best_sim >= threshold
                        and (not cfg.require_entity_match or _entity_compatible(rec, best_anchor, cfg))
                        and (not cfg.require_date_compatible or _date_compatible(rec, best_anchor))):
                    gid += 1
                    group_id = best_anchor.dup_group_id or gid
                    _mark(rec, best_anchor, group_id, "near_dup_tfidf", best_sim)
                else:
                    anchors.append(rec)
                    anchor_positions.append(pos_of[id(rec)])
            else:
                anchors.append(rec)
                anchor_positions.append(pos_of[id(rec)])
            done += 1
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)
    if progress:
        progress(total, total)
    return gid


def deduplicate(records: List[DedupRecord], cfg, progress: ProgressFn = None,
                 log: LogFn = None) -> List[DedupRecord]:
    gid = 0
    gid = _mark_exact(records, lambda r: r.file_sha256, "exact_file", gid)
    gid = _mark_exact(records, lambda r: r.text_sha256 if r.text_len > 0 else "", "exact_text", gid)
    _mark_near_duplicates(records, cfg, gid, progress=progress, log=log)
    return records
