"""classify.py — keyword-scored document type classification."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List

from .config import (
    CLASSIFICATION_KEYWORDS,
    CLASSIFICATION_PRIORITY,
    FALLBACK_TYPE,
    TITLE_BOOST,
    TITLE_ZONE_CHARS,
)


@dataclass
class ClassificationResult:
    doc_type: str
    score: float
    confidence: str
    needs_review: bool
    matched_terms: List[str] = field(default_factory=list)


def _keyword_score(text_lower: str, title_zone: str, keywords: List[str]):
    score = 0.0
    matched = []
    for kw in keywords:
        body_hits = text_lower.count(kw)
        if body_hits:
            title_hits = title_zone.count(kw)
            score += body_hits
            score += title_hits * (TITLE_BOOST - 1)
            matched.append(kw)
    return score, matched


def classify_document(text: str, thresholds) -> ClassificationResult:
    text = text or ""
    text_lower = text.lower()
    title_zone = text_lower[:TITLE_ZONE_CHARS]

    best_type = FALLBACK_TYPE
    best_score = 0.0
    best_matched: List[str] = []

    for doc_type in CLASSIFICATION_PRIORITY:
        keywords = CLASSIFICATION_KEYWORDS.get(doc_type, [])
        score, matched = _keyword_score(text_lower, title_zone, keywords)
        if score > best_score:
            best_score = score
            best_type = doc_type
            best_matched = matched

    if best_score <= 0:
        best_type = FALLBACK_TYPE

    if best_score >= thresholds.high_score:
        confidence = "HIGH"
    elif best_score >= thresholds.low_score:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    needs_review = confidence == "LOW" or best_type == FALLBACK_TYPE

    return ClassificationResult(
        doc_type=best_type,
        score=round(best_score, 2),
        confidence=confidence,
        needs_review=needs_review,
        matched_terms=best_matched,
    )
