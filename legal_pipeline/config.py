from __future__ import annotations
import datetime as _dt
import os as _os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


def desktop_output_dir(prefix: str = "LegalDocMigration") -> Path:
    home = Path(_os.path.expanduser("~"))
    desktop = home / "Desktop"
    if not desktop.exists():
        for cand in (home / "OneDrive" / "Desktop", home / "OneDrive - Documents" / "Desktop"):
            if cand.exists():
                desktop = cand; break
        else:
            desktop = home
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return desktop / f"{prefix}_{stamp}"


@dataclass
class Paths:
    source_dir: Path = Path("./input_pdfs")
    output_dir: Path = Path("./output")
    organised_dirname: str = "01_classified"
    consolidated_dirname: str = "Consolidated"   # flat folder of ALL retained files
    tracker_name: str = "migration_tracker.xlsx"
    text_cache_name: str = "extracted_text.cache.jsonl"

    def organised_dir(self) -> Path:
        return self.output_dir / self.organised_dirname

    def consolidated_dir(self) -> Path:
        return self.output_dir / self.consolidated_dirname

    def tracker_path(self) -> Path:
        return self.output_dir / self.tracker_name

    def cache_path(self) -> Path:
        return self.output_dir / self.text_cache_name


@dataclass
class Ingestion:
    min_native_chars: int = 120
    ocr_max_pages: int = 3
    ocr_dpi: int = 200
    ocr_lang: str = "eng"
    enable_ocr: bool = True
    tesseract_cmd: Optional[str] = None
    poppler_path: Optional[str] = None


CLASSIFICATION_KEYWORDS: Dict[str, List[str]] = {
    "Addendums": ["addendum", "amendment", "amendment agreement", "variation",
                  "change order", "supplemental agreement", "amendment no",
                  "amended and restated", "deed of variation", "side letter"],
    "Engagement Letters": ["engagement letter", "letter of engagement", "we are pleased to",
                           "scope of our services", "terms of engagement", "our engagement",
                           "engagement of services", "this letter sets out", "fee arrangement",
                           "audit engagement", "advisory engagement"],
    "Contracts": ["master services agreement", "services agreement", "contract",
                  "this agreement is made", "agreement between", "statement of work",
                  "consulting agreement", "purchase agreement", "framework agreement",
                  "terms and conditions", "in witness whereof", "hereinafter referred",
                  "non-disclosure agreement", "nda", "memorandum of understanding"],
}
CLASSIFICATION_PRIORITY: List[str] = ["Addendums", "Engagement Letters", "Contracts"]
FALLBACK_TYPE: str = "Other"
TITLE_BOOST: float = 2.5
TITLE_ZONE_CHARS: int = 1500


@dataclass
class ClassificationThresholds:
    high_score: float = 6.0
    low_score: float = 2.0


@dataclass
class Dedup:
    near_dup_similarity: float = 0.90
    min_chars_for_similarity: int = 200
    require_entity_match: bool = True
    require_date_compatible: bool = True
    block_by_type: bool = True


SERVICING_TEAMS: List[str] = ["Risk Advisory", "Audit", "Tax", "Consulting",
    "Financial Advisory", "Deals", "Assurance", "Internal Audit", "Cyber",
    "Forensic", "Legal", "Technology", "Strategy"]
MARKETS: List[str] = ["UAE", "United Arab Emirates", "Abu Dhabi", "Dubai", "KSA",
    "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman", "Egypt", "Jordan",
    "Lebanon", "United Kingdom", "UK", "United States", "USA", "India", "Singapore"]
SECTORS: List[str] = ["Banking", "Financial Services", "Insurance", "Healthcare",
    "Oil and Gas", "Energy", "Utilities", "Real Estate", "Construction", "Retail",
    "Technology", "Telecommunications", "Government", "Public Sector",
    "Manufacturing", "Transportation", "Aviation", "Hospitality", "Education", "Media"]
CURRENCY_TOKENS: Dict[str, str] = {
    "aed": "AED", "dhs": "AED", "dh": "AED", "درهم": "AED", "usd": "USD",
    "us$": "USD", "$": "USD", "sar": "SAR", "gbp": "GBP", "£": "GBP",
    "eur": "EUR", "€": "EUR", "qar": "QAR", "kwd": "KWD", "bhd": "BHD", "omr": "OMR"}


@dataclass
class Config:
    paths: Paths = field(default_factory=Paths)
    ingestion: Ingestion = field(default_factory=Ingestion)
    classify: ClassificationThresholds = field(default_factory=ClassificationThresholds)
    dedup: Dedup = field(default_factory=Dedup)


DEFAULT_CONFIG = Config()
