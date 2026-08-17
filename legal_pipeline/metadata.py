"""metadata.py — lightweight, regex-based metadata extraction for legal PDFs."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict

from dateutil import parser as _date_parser

from .config import SERVICING_TEAMS, MARKETS, SECTORS, CURRENCY_TOKENS

_ENTITY_SUFFIXES = (
    r"LLC|L\.L\.C\.|LLP|L\.L\.P\.|FZE|FZ-LLC|FZCO|PJSC|PSC|PLC|Ltd\.?|Limited|"
    r"Inc\.?|Corp\.?|Corporation|Co\.?|Company|Holdings?|Group|W\.L\.L\.|WLL"
)
_ENTITY_RE = re.compile(
    r"([A-Z][A-Za-z0-9&,.\-\s]{2,60}?\s(?:" + _ENTITY_SUFFIXES + r"))\b"
)
_BETWEEN_RE = re.compile(
    r"between\s+(.{3,80}?)\s+and\s+(.{3,80}?)[,.\n]", re.IGNORECASE
)
_CLIENT_LABEL_RE = re.compile(
    r"(?:client|customer|counterparty|company name)\s*[:\-]\s*(.{3,80})", re.IGNORECASE
)

_DATE_LABEL_RE = re.compile(
    r"(?:dated|effective date|date of (?:this )?agreement)\s*[:\-]?\s*"
    r"([^\n]{4,30})",
    re.IGNORECASE,
)
_DATE_LOOSE_RE = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}|"
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b"
)

_WS_RE = re.compile(r"\s+")


@dataclass
class DocMetadata:
    entity_name: str = ""
    contract_date: str = ""
    description: str = ""
    market: str = ""
    sector: str = ""
    servicing_team: str = ""
    currency: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(s: str) -> str:
    return _WS_RE.sub(" ", s or "").strip(" ,.-\t\n")


def _guess_entity_name(text: str) -> str:
    m = _CLIENT_LABEL_RE.search(text)
    if m:
        return _clean(m.group(1))[:80]

    m = _BETWEEN_RE.search(text)
    if m:
        for side in (m.group(1), m.group(2)):
            side_clean = _clean(side)
            if _ENTITY_RE.search(side_clean):
                return side_clean[:80]
        return _clean(m.group(1))[:80]

    m = _ENTITY_RE.search(text)
    if m:
        return _clean(m.group(1))[:80]

    return ""


def _guess_contract_date(text: str) -> str:
    m = _DATE_LABEL_RE.search(text)
    candidate = None
    if m:
        line = m.group(1)
        tight = _DATE_LOOSE_RE.search(line)
        candidate = tight.group(1) if tight else line
    else:
        m2 = _DATE_LOOSE_RE.search(text)
        if m2:
            candidate = m2.group(1)

    if not candidate:
        return ""

    try:
        dt = _date_parser.parse(candidate, fuzzy=True, dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        tight = _DATE_LOOSE_RE.search(candidate)
        if tight:
            try:
                dt = _date_parser.parse(tight.group(1), fuzzy=True, dayfirst=False)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        return _clean(candidate)[:20]


def _guess_description(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    for line in stripped.splitlines():
        line = _clean(line)
        if len(line) >= 15:
            return line[:160]
    return _clean(stripped)[:160]


def _first_match(text_lower: str, candidates) -> str:
    for c in candidates:
        if c.lower() in text_lower:
            return c
    return ""


def _guess_currency(text_lower: str) -> str:
    for token, normalised in CURRENCY_TOKENS.items():
        if token in text_lower:
            return normalised
    return ""


def extract_metadata(text: str) -> DocMetadata:
    text = text or ""
    text_lower = text.lower()

    return DocMetadata(
        entity_name=_guess_entity_name(text),
        contract_date=_guess_contract_date(text),
        description=_guess_description(text),
        market=_first_match(text_lower, MARKETS),
        sector=_first_match(text_lower, SECTORS),
        servicing_team=_first_match(text_lower, SERVICING_TEAMS),
        currency=_guess_currency(text_lower),
    )
"""metadata.py — lightweight, regex-based metadata extraction for legal PDFs."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Optional

from dateutil import parser as _date_parser

from .config import SERVICING_TEAMS, MARKETS, SECTORS, CURRENCY_TOKENS

_ENTITY_SUFFIXES = (
    r"LLC|L\.L\.C\.|LLP|L\.L\.P\.|FZE|FZ-LLC|FZCO|PJSC|PSC|PLC|Ltd\.?|Limited|"
    r"Inc\.?|Corp\.?|Corporation|Co\.?|Company|Holdings?|Group|W\.L\.L\.|WLL"
)
_ENTITY_RE = re.compile(
    r"([A-Z][A-Za-z0-9&,.\-\s]{2,60}?\s(?:" + _ENTITY_SUFFIXES + r"))\b"
)
_BETWEEN_RE = re.compile(
    r"between\s+(.{3,80}?)\s+and\s+(.{3,80}?)[,.\n]", re.IGNORECASE
)
_CLIENT_LABEL_RE = re.compile(
    r"(?:client|customer|counterparty|company name)\s*[:\-]\s*(.{3,80})", re.IGNORECASE
)

_DATE_LABEL_RE = re.compile(
    r"(?:dated|effective date|date of (?:this )?agreement)\s*[:\-]?\s*"
    r"([^\n]{4,30})",
    re.IGNORECASE,
)
_DATE_LOOSE_RE = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}|"
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b"
)

_WS_RE = re.compile(r"\s+")


@dataclass
class DocMetadata:
    entity_name: str = ""
    contract_date: str = ""
    description: str = ""
    market: str = ""
    sector: str = ""
    servicing_team: str = ""
    currency: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(s: str) -> str:
    return _WS_RE.sub(" ", s or "").strip(" ,.-\t\n")


def _guess_entity_name(text: str) -> str:
    m = _CLIENT_LABEL_RE.search(text)
    if m:
        return _clean(m.group(1))[:80]

    m = _BETWEEN_RE.search(text)
    if m:
        for side in (m.group(1), m.group(2)):
            side_clean = _clean(side)
            if _ENTITY_RE.search(side_clean):
                return side_clean[:80]
        return _clean(m.group(1))[:80]

    m = _ENTITY_RE.search(text)
    if m:
        return _clean(m.group(1))[:80]

    return ""


def _guess_contract_date(text: str) -> str:
    m = _DATE_LABEL_RE.search(text)
    candidate = None
    if m:
        line = m.group(1)
        tight = _DATE_LOOSE_RE.search(line)
        candidate = tight.group(1) if tight else line
    else:
        m2 = _DATE_LOOSE_RE.search(text)
        if m2:
            candidate = m2.group(1)

    if not candidate:
        return ""

    try:
        dt = _date_parser.parse(candidate, fuzzy=True, dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        tight = _DATE_LOOSE_RE.search(candidate)
        if tight:
            try:
                dt = _date_parser.parse(tight.group(1), fuzzy=True, dayfirst=False)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        return _clean(candidate)[:20]


def _guess_description(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    for line in stripped.splitlines():
        line = _clean(line)
        if len(line) >= 15:
            return line[:160]
    return _clean(stripped)[:160]


def _first_match(text_lower: str, candidates) -> str:
    for c in candidates:
        if c.lower() in text_lower:
            return c
    return ""


def _guess_currency(text_lower: str) -> str:
    for token, normalised in CURRENCY_TOKENS.items():
        if token in text_lower:
            return normalised
    return ""


def extract_metadata(text: str) -> DocMetadata:
    text = text or ""
    text_lower = text.lower()

    return DocMetadata(
        entity_name=_guess_entity_name(text),
        contract_date=_guess_contract_date(text),
        description=_guess_description(text),
        market=_first_match(text_lower, MARKETS),
        sector=_first_match(text_lower, SECTORS),
        servicing_team=_first_match(text_lower, SERVICING_TEAMS),
        currency=_guess_currency(text_lower),
    )
