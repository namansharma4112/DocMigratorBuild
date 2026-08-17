"""classify.py — content-based document type classification."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .config import (
    CLASSIFICATION_KEYWORDS,
    CATCH_ALL_CATEGORY,
    FALLBACK_TYPE,
    HEADING_ZONE_CHARS,
    TITLE_ZONE_CHARS,
    TITLE_BOOST,
    MAX_HITS_PER_KEYWORD,
    HEADING_ONLY_KEYWORDS,
    CANONICAL_HEADING_PHRASES,
    FUZZY_HEADING_THRESHOLD,
    MIN_FUZZY_PHRASE_LENGTH,
)

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEPARATOR_RE = re.compile(r"[_\-.]+")


@dataclass
class ClassificationResult:
    doc_type: str
    score: float
    confidence: str
    needs_review: bool
    matched_terms: List[str] = field(default_factory=list)


def _build_matcher(keywords_by_cat: Dict[str, List[str]]):
    pairs = []
    for cat, kws in keywords_by_cat.items():
        for kw in kws:
            pairs.append((kw, cat))
    pairs.sort(key=lambda p: -len(p[0]))
    parts = []
    group_to_kw_cat = {}
    for i, (kw, cat) in enumerate(pairs):
        group_name = f"K{i}"
        prefix = r"\b" if re.match(r"\w", kw[0]) else ""
        suffix = r"\b" if re.match(r"\w", kw[-1]) else ""
        parts.append(f"(?P<{group_name}>{prefix}{re.escape(kw)}{suffix})")
        group_to_kw_cat[group_name] = (kw, cat)
    pattern = re.compile("|".join(parts))
    return pattern, group_to_kw_cat


_PATTERN, _GROUP_MAP = _build_matcher(CLASSIFICATION_KEYWORDS)
_ALL_CATEGORIES = set(CLASSIFICATION_KEYWORDS.keys())
_SPECIFIC_CATEGORIES = _ALL_CATEGORIES - {CATCH_ALL_CATEGORY}

_HEADING_LINE_COUNT = 3


def _effective_heading_zone(text: str, char_cap: int) -> int:
    lines = text.split("\n")
    if len(lines) >= _HEADING_LINE_COUNT:
        boundary = sum(len(l) for l in lines[:_HEADING_LINE_COUNT]) + (_HEADING_LINE_COUNT - 1)
    else:
        boundary = len(text)
    return min(boundary, char_cap)


def _normalise_filename(file_name: str) -> str:
    if not file_name:
        return ""
    stem = Path(file_name).stem
    stem = _CAMEL_BOUNDARY_RE.sub(" ", stem)
    stem = _SEPARATOR_RE.sub(" ", stem)
    return stem.lower()


def _find_matches(text_lower: str):
    matches = []
    for m in _PATTERN.finditer(text_lower):
        kw, cat = _GROUP_MAP[m.lastgroup]
        matches.append((m.start(), cat, kw))
    return matches


def _is_heading_only(cat: str, kw: str) -> bool:
    return kw in HEADING_ONLY_KEYWORDS.get(cat, ())


def _fuzzy_heading_match(heading_text: str) -> Optional[Tuple[str, str, float]]:
    max_len = 100
    if len(heading_text) > max_len:
        heading_text = heading_text[:max_len]

    best: Optional[Tuple[str, str, float]] = None
    for cat, phrases in CANONICAL_HEADING_PHRASES.items():
        for phrase in phrases:
            n = len(phrase)
            if n < MIN_FUZZY_PHRASE_LENGTH:
                continue
            for window_len in range(max(1, n - 1), n + 2):
                for start in range(0, max(1, len(heading_text) - window_len + 1)):
                    window = heading_text[start:start + window_len]
                    ratio = SequenceMatcher(None, window, phrase).ratio()
                    if ratio >= FUZZY_HEADING_THRESHOLD and (best is None or ratio > best[2]):
                        best = (cat, phrase, ratio)
    return best


def classify_document(text: str, thresholds, file_name: str = "") -> ClassificationResult:
    text = text or ""
    text_lower = text.lower()
    filename_norm = _normalise_filename(file_name)

    body_raw = _find_matches(text_lower)
    filename_raw = _find_matches(filename_norm) if filename_norm else []

    heading_boundary = _effective_heading_zone(text_lower, HEADING_ZONE_CHARS)

    combined = [(start, cat, kw, start < heading_boundary) for start, cat, kw in body_raw]
    combined += [(start, cat, kw, True) for start, cat, kw in filename_raw]

    heading_cats: Set[str] = {cat for _s, cat, _kw, elig in combined if elig}
    specific_heading_cats = heading_cats & _SPECIFIC_CATEGORIES
    catch_all_in_heading = CATCH_ALL_CATEGORY in heading_cats

    def capped_scores(categories_allowed: Set[str]):
        scores = {cat: 0.0 for cat in categories_allowed}
        matched_terms: Dict[str, List[str]] = {cat: [] for cat in categories_allowed}
        hit_counts: Dict[tuple, int] = {}
        title_bonus_given: Set[str] = set()

        for start, cat, kw, elig in combined:
            if cat not in categories_allowed:
                continue
            if _is_heading_only(cat, kw) and not elig:
                continue
            key = (cat, kw)
            hit_counts[key] = hit_counts.get(key, 0) + 1
            if hit_counts[key] <= MAX_HITS_PER_KEYWORD:
                scores[cat] += 1.0
                matched_terms[cat].append(kw)
            if start < TITLE_ZONE_CHARS and cat not in title_bonus_given:
                scores[cat] += TITLE_BOOST
                title_bonus_given.add(cat)

        return scores, matched_terms

    def confidence_for(score: float) -> str:
        if score >= thresholds.high_score:
            return "HIGH"
        if score >= thresholds.low_score:
            return "MEDIUM"
        return "LOW"

    if len(specific_heading_cats) == 1:
        winning_cat = next(iter(specific_heading_cats))
        scores, matched_terms = capped_scores(_ALL_CATEGORIES)
        heading_terms = [f"heading:{kw}" for start, cat, kw, elig in combined
                         if cat == winning_cat and elig]
        return ClassificationResult(
            doc_type=winning_cat, score=round(scores.get(winning_cat, 0.0) + 100.0, 2),
            confidence="HIGH", needs_review=False,
            matched_terms=heading_terms or matched_terms.get(winning_cat, []),
        )

    if len(specific_heading_cats) == 0 and catch_all_in_heading:
        scores, matched_terms = capped_scores(_ALL_CATEGORIES)
        return ClassificationResult(
            doc_type=CATCH_ALL_CATEGORY, score=round(scores.get(CATCH_ALL_CATEGORY, 0.0) + 100.0, 2),
            confidence="HIGH", needs_review=False,
            matched_terms=matched_terms.get(CATCH_ALL_CATEGORY, []),
        )

    if len(specific_heading_cats) >= 2:
        scores, matched_terms = capped_scores(specific_heading_cats)
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        confidence = confidence_for(best_score)
        needs_review = confidence == "LOW"
        return ClassificationResult(
            doc_type=best_type, score=round(best_score, 2), confidence=confidence,
            needs_review=needs_review, matched_terms=matched_terms.get(best_type, []),
        )

    heading_zone_text = text_lower[:heading_boundary]
    fuzzy_result = _fuzzy_heading_match(heading_zone_text)
    fuzzy_filename_result = _fuzzy_heading_match(filename_norm) if filename_norm else None
    best_fuzzy = max(
        [r for r in (fuzzy_result, fuzzy_filename_result) if r is not None],
        key=lambda r: r[2], default=None,
    )
    if best_fuzzy is not None:
        fuzzy_cat, fuzzy_phrase, fuzzy_ratio = best_fuzzy
        scores, matched_terms = capped_scores(_ALL_CATEGORIES)
        return ClassificationResult(
            doc_type=fuzzy_cat, score=round(scores.get(fuzzy_cat, 0.0) + 90.0 * fuzzy_ratio, 2),
            confidence="HIGH", needs_review=False,
            matched_terms=[f"fuzzy:{fuzzy_phrase}({fuzzy_ratio:.2f})"],
        )

    scores, matched_terms = capped_scores(_ALL_CATEGORIES)
    best_type = max(scores, key=scores.get) if scores else FALLBACK_TYPE
    best_score = scores.get(best_type, 0.0)
    if best_score <= 0:
        best_type = FALLBACK_TYPE
    confidence = confidence_for(best_score)
    needs_review = confidence == "LOW" or best_type == FALLBACK_TYPE
    return ClassificationResult(
        doc_type=best_type, score=round(best_score, 2), confidence=confidence,
        needs_review=needs_review, matched_terms=matched_terms.get(best_type, []),
    )
