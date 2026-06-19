"""Hybrid retrieval helpers — RRF merge and score attribution."""

from __future__ import annotations

from collections.abc import Sequence

from teamshared.memory.types import MemoryRecord

RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[MemoryRecord]],
    *,
    k: int = RRF_K,
) -> list[MemoryRecord]:
    """Merge multiple ranked lists with reciprocal rank fusion.

    Each list contributes ``1 / (k + rank)`` to a record's fused score.
    Returns records sorted by fused score descending, deduped by ``id``.
    """
    scores: dict[str, float] = {}
    best: dict[str, MemoryRecord] = {}
    for lst in ranked_lists:
        for rank, rec in enumerate(lst, start=1):
            scores[rec.id] = scores.get(rec.id, 0.0) + 1.0 / (k + rank)
            if rec.id not in best:
                best[rec.id] = rec
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out: list[MemoryRecord] = []
    for rid, fused in ordered:
        rec = best[rid].model_copy(deep=True)
        rec.score = fused
        meta = dict(rec.metadata)
        meta["rrf_score"] = fused
        rec.metadata = meta
        out.append(rec)
    return out


def merge_vector_keyword(
    vector_hits: Sequence[MemoryRecord],
    keyword_hits: Sequence[MemoryRecord],
) -> list[MemoryRecord]:
    """RRF-merge vector and keyword hit lists."""
    return reciprocal_rank_fusion([vector_hits, keyword_hits])


def hit_at_k(
    ranked_ids: Sequence[str],
    expected_ids: Sequence[str],
    *,
    k: int = 5,
) -> float:
    """1.0 if any expected id appears in top-k, else 0.0."""
    expected = set(expected_ids)
    return 1.0 if any(rid in expected for rid in ranked_ids[:k]) else 0.0


def precision_at_k(
    ranked_ids: Sequence[str],
    expected_ids: Sequence[str],
    *,
    k: int = 5,
) -> float:
    """Fraction of the top-k slots filled by expected ids (standard P@k)."""
    if k <= 0:
        return 0.0
    expected = set(expected_ids)
    top = ranked_ids[:k]
    hits = sum(1 for rid in top if rid in expected)
    return hits / k
