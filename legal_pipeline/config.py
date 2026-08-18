from __future__ import annotations
import datetime as _dt
import os as _os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


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
    consolidated_dirname: str = "Consolidated"
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
    ocr_max_pages: Optional[int] = None
    ocr_dpi: int = 300
    ocr_lang: str = "eng"
    enable_ocr: bool = True
    tesseract_cmd: Optional[str] = None
    poppler_path: Optional[str] = None
    # --- performance (added; internal only, not surfaced in the GUI) ---
    # None -> auto-selected at runtime from CPU count. 1 == fully sequential
    # (identical behaviour to the pre-parallel version).
    max_workers: Optional[int] = None
    # Per-page OCR safety timeout (seconds). Guards against a single
    # pathological page hanging a worker forever. Generous so it never
    # trips on normal pages.
    ocr_page_timeout_sec: int = 240


CLASSIFICATION_KEYWORDS: Dict[str, List[str]] = {
    "GST Certificate": ["gst certificate", "gstin", "goods and services tax certificate",
                        "gst registration certificate", "certificate of registration",
                        "form gst reg"],
    "MSME Declaration": ["msme declaration", "udyam registration", "msme certificate",
                         "micro small and medium enterprises", "udyog aadhaar",
                         "msme registration certificate"],
    "PAN Card": ["permanent account number", "pan card", "income tax pan",
                 "pan no", "pan number", "income tax department"],
    "Invoice": ["invoice", "tax invoice", "invoice no", "invoice number",
                "proforma invoice", "commercial invoice", "bill of supply",
                "e-invoice", "gst invoice", "invoice#", "bill no"],
    "Cancelled Cheque": ["cancelled cheque", "cancelled check", "canceled cheque",
                        "voided cheque", "cancelled cheque copy"],
    "Challan": ["challan", "bank challan", "tax challan", "deposit challan",
               "gst challan", "payment challan"],
    "Payment Receipt": ["payment receipt", "receipt of payment", "cash receipt",
                        "official receipt", "receipt", "money receipt",
                        "payment voucher", "receipt no"],
    "Addendums": ["addendum", "amendment", "amendment agreement", "variation",
                  "change order", "supplemental agreement", "amendment no",
                  "amended and restated", "deed of variation", "side letter",
                  "amendment to agreement", "contract amendment"],
    "NDA": ["non-disclosure agreement", "nda", "non disclosure agreement",
            "mutual non-disclosure agreement", "mutual nda",
            "confidentiality agreement", "receiving party", "disclosing party",
            "confidential information disclosed", "confidentiality and non-disclosure agreement",
            "cnda"],
    "Engagement Letters": ["engagement letter", "letter of engagement", "we are pleased to",
                           "scope of our services", "terms of engagement", "our engagement",
                           "engagement of services", "fee arrangement",
                           "audit engagement", "advisory engagement"],
    "SOW": ["scope of work", "statement of work", "sow no", "sow number", "sow"],
    "Extension Letter": ["extension letter", "letter of extension", "contract extension",
                         "extend the term", "extension of contract", "renewal letter",
                         "contract renewal"],
    "Termination Letter": ["termination letter", "notice of termination", "letter of termination",
                           "termination of agreement", "termination of contract",
                           "notice to terminate", "contract termination notice"],
    "PO": ["purchase order", "po number", "po no", "purchase order no",
           "purchase order number", "po", "p.o.", "p.o", "po#"],
    "Letter of Intent": ["letter of intent", "loi", "intent to engage", "intent to purchase"],
    "Work Order": ["work order", "work order no", "work order number",
                   "task order", "service order", "job order", "wo no", "work order#"],
    "Order Form": ["order form", "sales order form"],
    "MOU": ["memorandum of understanding", "mou", "memorandum of agreement", "moa"],
    "Vendor Form": ["vendor form", "vendor details", "vendor registration", "vendor information",
                    "vendor master", "supplier registration", "supplier details", "vendor onboarding",
                    "new vendor creation form", "vendor master form", "supplier onboarding form"],
    "Contracts": ["master services agreement", "services agreement", "contract",
                  "this agreement is made", "consulting agreement", "purchase agreement",
                  "framework agreement"],
}

CLASSIFICATION_PRIORITY: List[str] = [
    "GST Certificate", "MSME Declaration", "PAN Card", "Invoice",
    "Cancelled Cheque", "Challan", "Payment Receipt",
    "Extension Letter", "Termination Letter", "PO", "Letter of Intent",
    "Work Order", "Order Form", "MOU", "Vendor Form",
    "Addendums", "NDA", "Engagement Letters", "SOW",
    "Contracts",
]

HEADING_ONLY_KEYWORDS: Dict[str, Set[str]] = {
    "GST Certificate": {"gst certificate", "gstin", "goods and services tax certificate",
                        "gst registration certificate", "certificate of registration",
                        "form gst reg"},
    "MSME Declaration": {"msme declaration", "udyam registration", "msme certificate",
                         "micro small and medium enterprises", "udyog aadhaar",
                         "msme registration certificate"},
    "PAN Card": {"permanent account number", "pan card", "income tax pan",
                 "pan no", "pan number", "income tax department"},
    "Invoice": {"invoice", "tax invoice", "invoice no", "invoice number",
                "proforma invoice", "commercial invoice", "bill of supply",
                "e-invoice", "gst invoice", "invoice#", "bill no"},
    "Cancelled Cheque": {"cancelled cheque", "cancelled check", "canceled cheque",
                        "voided cheque", "cancelled cheque copy"},
    "Challan": {"challan", "bank challan", "tax challan", "deposit challan",
               "gst challan", "payment challan"},
    "Payment Receipt": {"payment receipt", "receipt of payment", "cash receipt",
                        "official receipt", "receipt", "money receipt",
                        "payment voucher", "receipt no"},
    "Extension Letter": {"extension letter", "letter of extension", "contract extension",
                         "extend the term", "extension of contract", "renewal letter",
                         "contract renewal"},
    "Termination Letter": {"termination letter", "notice of termination", "letter of termination",
                           "termination of agreement", "termination of contract",
                           "notice to terminate", "contract termination notice"},
    "PO": {"purchase order", "po number", "po no", "purchase order no",
           "purchase order number", "po", "p.o.", "p.o", "po#"},
    "Letter of Intent": {"letter of intent", "loi", "intent to engage", "intent to purchase"},
    "Work Order": {"work order", "work order no", "work order number",
                   "task order", "service order", "job order", "wo no", "work order#"},
    "Order Form": {"order form", "sales order form"},
    "MOU": {"memorandum of understanding", "mou", "memorandum of agreement", "moa"},
    "Vendor Form": {"vendor form", "vendor details", "vendor registration", "vendor information",
                    "vendor master", "supplier registration", "supplier details", "vendor onboarding",
                    "new vendor creation form", "vendor master form", "supplier onboarding form"},
    "SOW": {"scope of work", "statement of work", "sow no", "sow number", "sow"},
}

CANONICAL_HEADING_PHRASES: Dict[str, List[str]] = {
    "GST Certificate": ["gst certificate"],
    "MSME Declaration": ["msme declaration", "udyam registration"],
    "PAN Card": ["pan card", "permanent account number"],
    "Invoice": ["invoice"],
    "Cancelled Cheque": ["cancelled cheque"],
    "Challan": ["challan"],
    "Payment Receipt": ["receipt"],
    "Extension Letter": ["extension letter"],
    "Termination Letter": ["termination letter"],
    "PO": ["purchase order"],
    "Letter of Intent": ["letter of intent"],
    "Work Order": ["work order"],
    "Order Form": ["order form"],
    "MOU": ["memorandum of understanding"],
    "Vendor Form": ["vendor form", "vendor registration"],
    "Addendums": ["addendum"],
    "NDA": ["non-disclosure agreement"],
    "Engagement Letters": ["engagement letter"],
    "SOW": ["scope of work", "statement of work"],
    "Contracts": ["services agreement"],
}

FUZZY_HEADING_THRESHOLD: float = 0.82
MIN_FUZZY_PHRASE_LENGTH: int = 7
CATCH_ALL_CATEGORY: str = "Contracts"
FALLBACK_TYPE: str = "Unclassified"

FOLDER_GROUP: Dict[str, str] = {
    "Extension Letter": "Others", "Termination Letter": "Others", "PO": "Others",
    "Letter of Intent": "Others", "Work Order": "Others", "Order Form": "Others",
    "MOU": "Others", "Vendor Form": "Others",
    "GST Certificate": "_DO_NOT_RETAIN", "MSME Declaration": "_DO_NOT_RETAIN",
    "PAN Card": "_DO_NOT_RETAIN", "Invoice": "_DO_NOT_RETAIN",
    "Cancelled Cheque": "_DO_NOT_RETAIN", "Challan": "_DO_NOT_RETAIN",
    "Payment Receipt": "_DO_NOT_RETAIN",
}

DELETE_DOC_TYPES: Set[str] = {
    "GST Certificate", "MSME Declaration", "PAN Card", "Invoice",
    "Cancelled Cheque", "Challan", "Payment Receipt",
}


def folder_group_for(doc_type: str) -> str:
    return FOLDER_GROUP.get(doc_type, doc_type)


HEADING_ZONE_CHARS: int = 100
TITLE_ZONE_CHARS: int = 1500
TITLE_BOOST: float = 3.0
MAX_HITS_PER_KEYWORD: int = 3


@dataclass
class ClassificationThresholds:
    high_score: float = 6.0
    low_score: float = 2.0


@dataclass
class Dedup:
    near_dup_similarity: float = 0.90
    near_dup_similarity_ocr: float = 0.80
    min_chars_for_similarity: int = 80
    require_entity_match: bool = True
    require_date_compatible: bool = True
    block_by_type: bool = True
    entity_fuzzy_threshold: float = 0.90


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
