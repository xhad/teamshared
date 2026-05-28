"""Pin Mem0's 2.x kwarg contract.

Mem0 2.0 tightened :meth:`Memory.get_all` / :meth:`Memory.search` to refuse
top-level ``user_id`` (must go inside ``filters``) and renamed ``limit`` to
``top_k``. We discovered this the hard way when ``memory_episodes_list``
returned a runtime error from the live server. These tests freeze the wire
format so a regression to the pre-2.0 signature is caught at unit-test time
instead of in production.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from teamshared.memory.semantic import SemanticEpisodicStore


@pytest.fixture
def store_with_fake_mem0() -> tuple[SemanticEpisodicStore, MagicMock]:
    """A :class:`SemanticEpisodicStore` whose Mem0 client is a MagicMock.

    We bypass :meth:`SemanticEpisodicStore.connect` (which would import and
    instantiate real Mem0) by assigning ``_memory`` directly.
    """
    store = SemanticEpisodicStore.__new__(SemanticEpisodicStore)
    fake = MagicMock()
    fake.get_all.return_value = {"results": []}
    fake.search.return_value = {"results": []}
    store._memory = fake  # type: ignore[attr-defined]
    return store, fake


async def test_list_episodes_uses_filters_not_top_level_user_id(
    store_with_fake_mem0: tuple[SemanticEpisodicStore, MagicMock],
) -> None:
    store, fake = store_with_fake_mem0

    await store.list_episodes(agent="cursor", limit=10)

    fake.get_all.assert_called_once()
    kwargs: dict[str, Any] = fake.get_all.call_args.kwargs
    assert "user_id" not in kwargs, (
        "Mem0 2.0 forbids top-level user_id on get_all(); pass via filters instead"
    )
    assert "limit" not in kwargs, "Mem0 2.0 renamed limit to top_k"
    assert kwargs.get("filters") == {"user_id": "cursor"}
    assert kwargs.get("top_k") == 50  # max(limit*4, 50)


async def test_list_episodes_omits_filters_when_no_agent(
    store_with_fake_mem0: tuple[SemanticEpisodicStore, MagicMock],
) -> None:
    store, fake = store_with_fake_mem0

    await store.list_episodes(limit=5)

    kwargs: dict[str, Any] = fake.get_all.call_args.kwargs
    assert "filters" not in kwargs
    assert "user_id" not in kwargs


async def test_search_passes_user_id_and_pillar_via_filters(
    store_with_fake_mem0: tuple[SemanticEpisodicStore, MagicMock],
) -> None:
    store, fake = store_with_fake_mem0

    await store.search("anything", agent="hermes", pillar="episodic", limit=3)

    kwargs: dict[str, Any] = fake.search.call_args.kwargs
    assert "user_id" not in kwargs
    assert "limit" not in kwargs
    assert kwargs.get("filters") == {"user_id": "hermes", "pillar": "episodic"}


async def test_search_overfetches_and_disables_threshold(
    store_with_fake_mem0: tuple[SemanticEpisodicStore, MagicMock],
) -> None:
    """Mem0 2.0's ``score_and_rank`` filters with ``score < threshold`` (default
    0.1) and sorts DESC, but pgvector reports cosine *distance* in ``score``.
    The net effect is that the best matches are dropped. We work around it by
    over-fetching and disabling the threshold; teamshared then flips and re-ranks
    correctly. Pin both kwargs so a regression to the small-``top_k`` /
    default-threshold call shape is caught here.
    """
    store, fake = store_with_fake_mem0

    await store.search("q", agent="cursor", limit=3)

    kwargs: dict[str, Any] = fake.search.call_args.kwargs
    assert kwargs.get("threshold") == 0.0
    assert kwargs.get("top_k") == 50  # max(3 * 10, 50)

    await store.search("q", agent="cursor", limit=20)
    kwargs = fake.search.call_args.kwargs
    assert kwargs.get("top_k") == 200  # max(20 * 10, 50)


async def test_search_omits_filters_when_no_agent_no_pillar(
    store_with_fake_mem0: tuple[SemanticEpisodicStore, MagicMock],
) -> None:
    store, fake = store_with_fake_mem0

    await store.search("anything", limit=8)

    kwargs: dict[str, Any] = fake.search.call_args.kwargs
    assert "filters" not in kwargs
    assert kwargs.get("top_k") == 80  # max(8 * 10, 50)


async def test_search_inverts_mem0_distance_into_similarity(
    store_with_fake_mem0: tuple[SemanticEpisodicStore, MagicMock],
) -> None:
    """Mem0's pgvector backend reports cosine *distance* in the ``score`` field
    (smaller = better). teamshared contract is similarity (larger = better). The
    boundary in :meth:`SemanticEpisodicStore.search` must flip them so the
    cross-pillar reranker, sort order, and any downstream consumer all agree.
    """
    store, fake = store_with_fake_mem0
    fake.search.return_value = {
        "results": [
            {"id": "near", "memory": "very close", "score": 0.1,
             "metadata": {"pillar": "semantic"}},
            {"id": "far", "memory": "barely related", "score": 0.9,
             "metadata": {"pillar": "semantic"}},
            {"id": "orthogonal", "memory": "unrelated", "score": 1.5,
             "metadata": {"pillar": "semantic"}},
        ]
    }

    records = await store.search("q", limit=3)

    by_id = {r.id: r for r in records}
    assert by_id["near"].score == pytest.approx(0.9)
    assert by_id["far"].score == pytest.approx(0.1)
    assert by_id["orthogonal"].score == 0.0  # clamped, no negative similarities
