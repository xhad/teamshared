"""Cross-pillar recall: merge results from working, semantic, episodic, procedural.

Strategy:

1. Fan out to every requested pillar in parallel.
2. Normalize each result to :class:`MemoryRecord`.
3. Re-rank using a simple weighted score (vector score with a small recency
   boost for episodic + working). This is intentionally dumb to start; we can
   swap in a reranker model later without touching the tool surface.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

from sptx.logging import get_logger
from sptx.memory.procedural import ProceduralStore
from sptx.memory.semantic import SemanticEpisodicStore
from sptx.memory.types import MemoryRecord, MemoryScope, RecallResult, TimeRange
from sptx.memory.working import WorkingMemory

log = get_logger(__name__)

DEFAULT_SCOPE: tuple[MemoryScope, ...] = ("semantic", "episodic", "procedural", "working")

PILLAR_WEIGHTS: dict[str, float] = {
    "semantic": 1.0,
    "episodic": 0.9,
    "procedural": 0.85,
    "working": 0.7,
}


class Recall:
    """Top-level facade used by the MCP recall tool."""

    def __init__(
        self,
        working: WorkingMemory,
        semantic_episodic: SemanticEpisodicStore,
        procedural: ProceduralStore,
    ) -> None:
        self.working = working
        self.semantic_episodic = semantic_episodic
        self.procedural = procedural

    async def search(
        self,
        query: str,
        *,
        agent: str | None = None,
        caller: str | None = None,
        scopes: Iterable[MemoryScope] = DEFAULT_SCOPE,
        k: int = 8,
        time_range: TimeRange | None = None,
    ) -> RecallResult:
        """Hybrid recall.

        ``agent`` is an *opt-in* filter on the durable pillars (semantic +
        episodic): pass ``"cursor"`` to see only cursor's writes, leave it
        ``None`` to see every agent's writes. The "shared brain" promise lives
        here — without an explicit filter the durable pillars are unscoped.

        ``caller`` is the bearer-token identity of the requester. It only
        controls which working-memory session we surface (working memory is
        ephemeral per-session conversation buffer, so cross-agent visibility
        there would be noise). When ``caller`` is ``None`` we skip working
        memory entirely.
        """
        scopes_tuple = tuple(scopes)
        tr_tuple = (
            (time_range.since, time_range.until) if time_range else (None, None)
        )

        tasks: list[asyncio.Task[list[MemoryRecord]]] = []
        kinds: list[MemoryScope] = []

        if "semantic" in scopes_tuple or "all" in scopes_tuple:
            tasks.append(
                asyncio.create_task(
                    self.semantic_episodic.search(
                        query, agent=agent, pillar="semantic", limit=k, time_range=tr_tuple
                    )
                )
            )
            kinds.append("semantic")
        if "episodic" in scopes_tuple or "all" in scopes_tuple:
            tasks.append(
                asyncio.create_task(
                    self.semantic_episodic.search(
                        query, agent=agent, pillar="episodic", limit=k, time_range=tr_tuple
                    )
                )
            )
            kinds.append("episodic")
        if "procedural" in scopes_tuple or "all" in scopes_tuple:
            tasks.append(
                asyncio.create_task(self.procedural.search_procedures(query, limit=k))
            )
            kinds.append("procedural")
        if ("working" in scopes_tuple or "all" in scopes_tuple) and caller:
            tasks.append(
                asyncio.create_task(self.working.recent_records(caller, k=k))
            )
            kinds.append("working")

        per_pillar = await asyncio.gather(*tasks, return_exceptions=True)

        records: list[MemoryRecord] = []
        counts: dict[str, int] = {}
        for kind, result in zip(kinds, per_pillar, strict=True):
            if isinstance(result, BaseException):
                log.warning("recall_pillar_failed", pillar=kind, error=str(result))
                counts[kind] = 0
                continue
            counts[kind] = len(result)
            records.extend(result)

        ranked = _rerank(records, k=k)
        return RecallResult(query=query, records=ranked, counts_by_pillar=counts)


def _rerank(records: list[MemoryRecord], *, k: int) -> list[MemoryRecord]:
    """Stable rerank by ``weighted = score * pillar_weight + recency_bonus``."""
    now = datetime.now(UTC)

    def score_of(r: MemoryRecord) -> float:
        base = r.score if r.score is not None else 0.5
        weight = PILLAR_WEIGHTS.get(r.pillar, 0.5)
        recency_bonus = 0.0
        if r.created_at and r.pillar in {"episodic", "working"}:
            age_hours = max((now - r.created_at).total_seconds() / 3600.0, 0.0)
            recency_bonus = max(0.0, 0.2 * (1.0 / (1.0 + age_hours / 24.0)))
        return base * weight + recency_bonus

    return sorted(records, key=score_of, reverse=True)[:k]
