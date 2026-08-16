"""dedupe.py — three-tier deduplication: exact file, exact text, near-duplicate."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, List, Optional

try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False

ProgressFn = Optional[Callable[[int, int], None]]


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


def _entity_compatible(a: DedupRecord, b: DedupRecord) -> bool:
    ea, eb = (a.entity_name or "").strip().lower(), (b.entity_name or "").strip().lower()
    if not ea or not eb:
        return True
    return ea == eb


def _date_compatible(a: DedupRecord, b: DedupRecord) -> bool:
    da, db = (a.contract_date or "").strip(), (b.contract_date or "").strip()
    if not da or not db:
        return True
    return da == db


def _mark_near_duplicates(records: List[DedupRecord], cfg, group_id_start: int,
                           progress: ProgressFn = None) -> int:
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
        bucket_list = list(buckets.values())
    else:
        bucket_list = [candidates]

    total = len(candidates)
    done = 0

    for bucket in bucket_list:
        if len(bucket) < 2:
            done += len(bucket)
            if progress:
                progress(done, total)
            continue
        bucket.sort(key=lambda r: r.idx)
        pos_of = {id(r): i for i, r in enumerate(bucket)}

        if _HAS_SKLEARN:
            try:
                vec = TfidfVectorizer(min_df=1)
                matrix = vec.fit_transform([r.text_norm for r in bucket])
                sim_matrix = cosine_similarity(matrix)
            except Exception:
                sim_matrix = None
        else:
            sim_matrix = None

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
                if sim_matrix is not None:
                    sims = sim_matrix[i, anchor_positions]
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

            if (best_anchor is not None and best_sim >= cfg.near_dup_similarity
                    and (not cfg.require_entity_match or _entity_compatible(rec, best_anchor))
                    and (not cfg.require_date_compatible or _date_compatible(rec, best_anchor))):
                gid += 1
                group_id = best_anchor.dup_group_id or gid
                _mark(rec, best_anchor, group_id, "near_dup_tfidf", best_sim)
            else:
                anchors.append(rec)
                anchor_positions.append(pos_of[id(rec)])

            done += 1
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)

    if progress:
        progress(total, total)
    return gid


def deduplicate(records: List[DedupRecord], cfg, progress: ProgressFn = None) -> List[DedupRecord]:
    gid = 0
    gid = _mark_exact(records, lambda r: r.file_sha256, "exact_file", gid)
    gid = _mark_exact(records, lambda r: r.text_sha256 if r.text_len > 0 else "", "exact_text", gid)
    _mark_near_duplicates(records, cfg, gid, progress=progress)
    return records
