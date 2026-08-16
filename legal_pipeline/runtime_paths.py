"""runtime_paths.py — locate bundled Tesseract/Poppler for OCR in the .exe."""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple


def _base_dirs():
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
    else:
        dirs.append(Path(__file__).resolve().parent.parent)
    return dirs


def _find_tesseract() -> Optional[str]:
    for base in _base_dirs():
        for cand in [base / "vendor" / "tesseract" / "tesseract.exe",
                     base / "vendor" / "tesseract" / "tesseract"]:
            if cand.exists():
                tessdata = cand.parent / "tessdata"
                if tessdata.exists():
                    os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                return str(cand)
    return shutil.which("tesseract")


def _find_poppler() -> Optional[str]:
    for base in _base_dirs():
        for cand in [base / "vendor" / "poppler" / "bin",
                     base / "vendor" / "poppler" / "Library" / "bin",
                     base / "vendor" / "poppler"]:
            if (cand / "pdftoppm.exe").exists() or (cand / "pdftoppm").exists():
                return str(cand)
    found = shutil.which("pdftoppm")
    return str(Path(found).parent) if found else None


def resolve_ocr_binaries() -> Tuple[Optional[str], Optional[str]]:
    return _find_tesseract(), _find_poppler()


def apply_to_config(cfg):
    tcmd, ppath = resolve_ocr_binaries()
    cfg.ingestion.tesseract_cmd = tcmd
    cfg.ingestion.poppler_path = ppath
    if not tcmd:
        cfg.ingestion.enable_ocr = False
    return tcmd, ppath
