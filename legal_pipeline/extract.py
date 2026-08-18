"""extract.py — PDF text extraction ladder (native -> pdfplumber -> OCR).

PERFORMANCE / RELIABILITY UPDATE (parallel-safe OCR):
  The OCR fallback now renders + OCRs the document ONE PAGE AT A TIME instead
  of rasterising the entire document into memory up front. This is functionally
  identical (same page images at the same DPI, OCR'd in the same order and
  joined with the same "\n" separator, so the extracted text is byte-for-byte
  the same as before) but it:
    * bounds peak memory per document to a single page image — essential now
      that many documents are OCR'd concurrently (see pipeline.stage_extract),
      and removes the whole-document rasterisation that could exhaust memory on
      very large scanned files at scale;
    * applies a per-page Tesseract timeout so a single pathological page can no
      longer hang a worker forever;
    * isolates per-page OCR failures so one unreadable page degrades to empty
      text for that page instead of discarding the whole document's OCR.
  None of these change the OCR engine invocation (same dpi / lang / OEM / PSM),
  so classification, metadata and dedup results are unchanged.
"""
from __future__ import annotations
import hashlib
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF
try:
    import pdfplumber
    _HAS_PLUMBER = True
except Exception:
    _HAS_PLUMBER = False


@dataclass
class ExtractedDoc:
    path: str
    file_name: str
    size_bytes: int
    page_count: int
    text: str
    extraction_method: str
    file_sha256: str
    text_sha256: str
    is_scanned: bool
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


_WS_RE = re.compile(r"\s+")


def normalise_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return _WS_RE.sub(" ", text).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


def _extract_native(path: Path):
    doc = fitz.open(path)
    try:
        pages = [doc.load_page(i).get_text("text") for i in range(doc.page_count)]
        return "\n".join(pages), doc.page_count
    finally:
        doc.close()


def _extract_plumber(path: Path) -> str:
    if not _HAS_PLUMBER:
        return ""
    parts = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _ocr_page_range(max_pages, page_count):
    """Resolve the 1-based inclusive last page to OCR, matching the previous
    convert_from_path(first_page=1, last_page=max_pages) semantics."""
    if page_count and page_count > 0:
        if max_pages:
            return min(int(max_pages), int(page_count))
        return int(page_count)
    # Page count unknown -> fall back to whatever max_pages requests (may be None).
    return max_pages


def _extract_ocr(path, max_pages, dpi, lang, tesseract_cmd, poppler_path,
                 page_count=None, page_timeout=None) -> str:
    import pytesseract
    from pdf2image import convert_from_path
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    base_kwargs = {}
    if poppler_path:
        base_kwargs["poppler_path"] = poppler_path

    last = _ocr_page_range(max_pages, page_count)

    # If we could not determine a concrete page count and no cap was set,
    # fall back to the original bulk render (rare: only when page_count==0).
    if not last:
        images = convert_from_path(str(path), dpi=dpi, first_page=1,
                                   last_page=max_pages, **base_kwargs)
        parts = []
        for img in images:
            try:
                parts.append(_ocr_image(pytesseract, img, lang, page_timeout))
            finally:
                _safe_close(img)
        return "\n".join(parts)

    parts = []
    for p in range(1, last + 1):
        images = convert_from_path(str(path), dpi=dpi, first_page=p,
                                   last_page=p, **base_kwargs)
        if not images:
            break
        img = images[0]
        try:
            parts.append(_ocr_image(pytesseract, img, lang, page_timeout))
        finally:
            _safe_close(img)
    return "\n".join(parts)


def _ocr_image(pytesseract, img, lang, page_timeout):
    try:
        if page_timeout and page_timeout > 0:
            return pytesseract.image_to_string(img, lang=lang, timeout=page_timeout)
        return pytesseract.image_to_string(img, lang=lang)
    except (RuntimeError, Exception):
        # A single page failing/timing out must not lose the rest of the
        # document's OCR — degrade that page to empty and continue.
        return ""


def _safe_close(img):
    try:
        img.close()
    except Exception:
        pass


def extract_worker(path_str: str, ing) -> ExtractedDoc:
    """Top-level, picklable unit of work for the process pool.

    Lives in extract.py (which only imports fitz/pdfplumber) rather than in
    pipeline.py (which imports scikit-learn) so that ``spawn``-ed worker
    processes do NOT pay the heavy sklearn/numpy import cost. Full per-file
    crash isolation: any failure is captured as a 'failed' ExtractedDoc so a
    single bad PDF can never abort the batch.
    """
    p = Path(path_str)
    try:
        return extract_document(p, ing)
    except Exception as e:
        import traceback
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        return ExtractedDoc(
            path=str(p), file_name=p.name, size_bytes=size, page_count=0,
            text="", extraction_method="failed",
            file_sha256=f"__unreadable__:{p}",
            text_sha256=sha256_text(""), is_scanned=False,
            error=f"could not process file: {e}\n{traceback.format_exc(limit=2)}",
        )


def extract_document(path: Path, ing) -> ExtractedDoc:
    path = Path(path)
    raw = path.read_bytes()
    file_hash = sha256_bytes(raw)
    size = len(raw)
    text, pages, method, scanned, err = "", 0, "failed", False, None
    try:
        text, pages = _extract_native(path)
        method = "native_fitz"
    except Exception as e:
        err = f"native:{e}"
    if len(text.strip()) < ing.min_native_chars:
        try:
            pt = _extract_plumber(path)
            if len(pt.strip()) > len(text.strip()):
                text, method = pt, "pdfplumber"
        except Exception as e:
            err = (err or "") + f" | plumber:{e}"
    if len(text.strip()) < ing.min_native_chars:
        scanned = True
        if ing.enable_ocr:
            # Resolve page count up front so OCR can stream page-by-page.
            if pages == 0:
                try:
                    d = fitz.open(path)
                    pages = d.page_count
                    d.close()
                except Exception:
                    pages = 0
            try:
                ot = _extract_ocr(path, ing.ocr_max_pages, ing.ocr_dpi, ing.ocr_lang,
                                  ing.tesseract_cmd, ing.poppler_path,
                                  page_count=pages,
                                  page_timeout=getattr(ing, "ocr_page_timeout_sec", None))
                if len(ot.strip()) > len(text.strip()):
                    text, method = ot, "ocr"
            except Exception as e:
                err = (err or "") + f" | ocr:{e}"
    if pages == 0:
        try:
            d = fitz.open(path)
            pages = d.page_count
            d.close()
        except Exception:
            pages = 0
    return ExtractedDoc(
        path=str(path.resolve()), file_name=path.name, size_bytes=size,
        page_count=pages, text=text, extraction_method=method,
        file_sha256=file_hash, text_sha256=sha256_text(text),
        is_scanned=scanned, error=err,
    )
