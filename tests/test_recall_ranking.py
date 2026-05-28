"""Unit tests for the cross-pillar rerank logic and the agent/caller contract.

We don't connect any backing store; we feed synthetic records into ``_rerank``
to verify pillar weighting and recency boost, and we wire ``Recall`` up to
mocks to pin the cross-agent visibility contract (shared by default, opt-in
to filter).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.memory.recall import Recall, _rerank
from teamshared.memory.types import MemoryRecord


def _mk(
    pillar: str,
    score: float,
    *,
    age_hours: float | None = None,
    content: str = "x",
) -> MemoryRecord:
    return MemoryRecord(
        id=f"{pillar}-{score}-{age_hours}",
        pillar=pillar,  # type: ignore[arg-type]
        content=content,
        score=score,
        created_at=(datetime.now(UTC) - timedelta(hours=age_hours)) if age_hours is not None else None,
    )


def test_higher_score_outranks_lower() -> None:
    out = _rerank([_mk("semantic", 0.4), _mk("semantic", 0.8)], k=2)
    assert out[0].score == 0.8


def test_semantic_outranks_procedural_at_equal_score() -> None:
    out = _rerank([_mk("procedural", 0.9), _mk("semantic", 0.9)], k=2)
    assert out[0].pillar == "semantic"


def test_recent_episodic_gets_boost_over_old_episodic() -> None:
    out = _rerank(
        [
            _mk("episodic", 0.5, age_hours=240),
            _mk("episodic", 0.5, age_hours=1),
        ],
        k=2,
    )
    assert out[0].created_at is not None
    assert (datetime.now(UTC) - out[0].created_at).total_seconds() < 3600 * 2


def test_k_truncation() -> None:
    records = [_mk("semantic", 0.1 * i) for i in range(10)]
    out = _rerank(records, k=3)
    assert len(out) == 3


@pytest.fixture
def recall_with_mocks() -> tuple[Recall, MagicMock, MagicMock, MagicMock]:
    semantic = MagicMock()
    semantic.search = AsyncMock(return_value=[])
    procedural = MagicMock()
    procedural.search_procedures = AsyncMock(return_value=[])
    working = MagicMock()
    working.recent_records = AsyncMock(return_value=[])
    return Recall(working=working, semantic_episodic=semantic, procedural=procedural), \
        semantic, procedural, working


async def test_recall_search_does_not_filter_durable_pillars_by_default(
    recall_with_mocks: tuple[Recall, MagicMock, MagicMock, MagicMock],
) -> None:
    """The shared brain promise lives in ``Recall.search``: with no ``agent``
    argument, semantic and episodic queries must hit Mem0 with no agent
    filter so every agent's writes are reachable.
    """
    recall, semantic, _, _ = recall_with_mocks

    await recall.search("anything", caller="cursor", scopes=("semantic", "episodic"))

    assert semantic.search.await_count == 2
    for call in semantic.search.await_args_list:
        assert call.kwargs["agent"] is None


async def test_recall_search_filters_when_agent_explicitly_set(
    recall_with_mocks: tuple[Recall, MagicMock, MagicMock, MagicMock],
) -> None:
    recall, semantic, _, _ = recall_with_mocks

    await recall.search(
        "anything", agent="hermes", caller="cursor", scopes=("semantic",)
    )

    semantic.search.assert_awaited_once()
    assert semantic.search.await_args.kwargs["agent"] == "hermes"


async def test_recall_search_uses_caller_for_working_memory_only(
    recall_with_mocks: tuple[Recall, MagicMock, MagicMock, MagicMock],
) -> None:
    """Working memory is per-session conversation state. We always look it up
    by the requester's identity (``caller``), never by the ``agent`` filter,
    because surfacing another agent's mid-conversation buffer is noise.
    """
    recall, _, _, working = recall_with_mocks

    await recall.search(
        "anything", agent="hermes", caller="cursor", scopes=("working",)
    )

    working.recent_records.assert_awaited_once_with("cursor", k=8)


async def test_recall_search_skips_working_when_caller_unbound(
    recall_with_mocks: tuple[Recall, MagicMock, MagicMock, MagicMock],
) -> None:
    """Without a caller identity (e.g. anonymous + auth disabled in dev) we
    have no session to look up, so working memory is silently skipped.
    """
    recall, _, _, working = recall_with_mocks

    await recall.search("anything", scopes=("working", "semantic"))

    working.recent_records.assert_not_awaited()


async def test_recall_search_surfaces_pillar_errors(
    recall_with_mocks: tuple[Recall, MagicMock, MagicMock, MagicMock],
) -> None:
    recall, semantic, _, _ = recall_with_mocks
    semantic.search = AsyncMock(side_effect=RuntimeError("mem0 unavailable"))

    result = await recall.search("anything", scopes=("semantic",))

    assert result.records == []
    assert result.counts_by_pillar.get("semantic") == 0
    assert "mem0 unavailable" in result.errors_by_pillar.get("semantic", "")


async def test_recall_search_procedural_is_globally_visible(
    recall_with_mocks: tuple[Recall, MagicMock, MagicMock, MagicMock],
) -> None:
    """Procedural memory has always been shared (no agent filter on read).
    Pinning that so a future refactor doesn't accidentally narrow it.
    """
    recall, _, procedural, _ = recall_with_mocks

    await recall.search("x", agent="hermes", scopes=("procedural",))

    procedural.search_procedures.assert_awaited_once_with("x", limit=8)
