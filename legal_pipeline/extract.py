"""extract.py — PDF text extraction ladder (native -> pdfplumber -> OCR)."""
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


def _extract_ocr(path, max_pages, dpi, lang, tesseract_cmd, poppler_path) -> str:
    import pytesseract
    from pdf2image import convert_from_path
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    kwargs = dict(dpi=dpi, first_page=1, last_page=max_pages)
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    images = convert_from_path(str(path), **kwargs)
    return "\n".join(pytesseract.image_to_string(img, lang=lang) for img in images)


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
            try:
                ot = _extract_ocr(path, ing.ocr_max_pages, ing.ocr_dpi, ing.ocr_lang,
                                  ing.tesseract_cmd, ing.poppler_path)
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
