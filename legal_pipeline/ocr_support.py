"""ocr_support.py — OCR engine detection/configuration.

v1.3 fix (2026-08-16): search paths harmonised with runtime_paths.py
(both now check vendor/poppler/bin AND vendor/poppler/Library/bin), since
a mismatch between the two independent detection mechanisms was the root
cause of a misleading "OCR unavailable" status message being shown even
when OCR was actually working (see pipeline.py's run() for the accompanying
fix that also stops this module from being called at all when the caller
has already supplied working tesseract_cmd/poppler_path values directly).
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class OCRStatus:
    ready: bool
    tesseract_path: Optional[str] = None
    poppler_path: Optional[str] = None
    engine_version: Optional[str] = None
    messages: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ready:
            ver = f" (v{self.engine_version})" if self.engine_version else ""
            return f"OCR ready{ver} — tesseract: {self.tesseract_path}"
        if self.messages:
            return "OCR unavailable — " + "; ".join(self.messages)
        return "OCR unavailable — tesseract/poppler not found"


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _candidate_dirs(*subfolders: str) -> List[Path]:
    root = _bundle_root()
    candidates = []
    for sub in subfolders:
        candidates.append(root / sub)
        candidates.append(root / "vendor" / sub)
        candidates.append(root / "ocr_helpers" / sub)
    return candidates


def _find_executable(name: str, bundled_subfolders: List[str]) -> Optional[str]:
    for folder in _candidate_dirs(*bundled_subfolders):
        candidate = folder / name
        if candidate.exists():
            return str(candidate)
        bin_candidate = folder / "bin" / name
        if bin_candidate.exists():
            return str(bin_candidate)
    found = shutil.which(name)
    if found:
        return found
    return None


def configure_ocr() -> OCRStatus:
    messages: List[str] = []

    tesseract_exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    tesseract_path = _find_executable(tesseract_exe, ["tesseract", "Tesseract-OCR"])

    poppler_exe = "pdftoppm.exe" if os.name == "nt" else "pdftoppm"
    # v1.3 fix: added "poppler/Library/bin" - matches runtime_paths.py and
    # matches the actual folder layout produced by the oschwartz10612
    # poppler-windows release used in build.yml (conda-forge style:
    # Library/bin/pdftoppm.exe, not a plain bin/pdftoppm.exe).
    poppler_exec_path = _find_executable(poppler_exe, ["poppler", "poppler/bin",
                                                        "poppler/Library/bin", "poppler-bin"])
    poppler_bin_dir = str(Path(poppler_exec_path).parent) if poppler_exec_path else None

    if not tesseract_path:
        messages.append("tesseract.exe not found (checked bundled folders and PATH)")
    if not poppler_exec_path:
        messages.append("poppler (pdftoppm) not found (checked bundled folders and PATH)")

    engine_version = None
    if tesseract_path:
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            try:
                engine_version = str(pytesseract.get_tesseract_version())
            except Exception as e:
                messages.append(f"could not read tesseract version: {e}")
        except ImportError:
            messages.append("pytesseract package not installed")
            tesseract_path = None

    global _POPPLER_BIN_DIR
    _POPPLER_BIN_DIR = poppler_bin_dir

    if poppler_bin_dir and poppler_bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = poppler_bin_dir + os.pathsep + os.environ.get("PATH", "")

    ready = bool(tesseract_path and poppler_exec_path)

    return OCRStatus(
        ready=ready,
        tesseract_path=tesseract_path,
        poppler_path=poppler_bin_dir,
        engine_version=engine_version,
        messages=messages,
    )


_POPPLER_BIN_DIR: Optional[str] = None
_LAST_STATUS: Optional[OCRStatus] = None


def is_ocr_ready() -> bool:
    global _LAST_STATUS
    if _LAST_STATUS is None:
        _LAST_STATUS = configure_ocr()
    return _LAST_STATUS.ready
