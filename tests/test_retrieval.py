"""Retrieval pipeline pure-logic tests: rerank, RRF merge, and scope recheck."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from teamshared.memory.hybrid import reciprocal_rank_fusion
from teamshared.memory.retrieval import SecureRetrieval, _recheck_scope, _rerank
from teamshared.memory.types import MemoryRecord
from teamshared.memory.vectorstore import ScopeFilter


def _rec(id_: str, *, pillar: str = "semantic", score: float = 0.5, **kw: object) -> MemoryRecord:
    return MemoryRecord(id=id_, pillar=pillar, content=id_, score=score, **kw)  # type: ignore[arg-type]


def test_rerank_orders_by_weighted_score() -> None:
    a = _rec("a", pillar="semantic", score=0.6)
    b = _rec("b", pillar="working", score=0.6)
    ranked = _rerank([b, a], k=10)
    assert ranked[0].id == "a"  # semantic weight > working weight


def test_rrf_merge_dedupes() -> None:
    a = _rec("x")
    b = _rec("x")
    c = _rec("y")
    merged = reciprocal_rank_fusion([[a], [b, c]])
    assert {r.id for r in merged} == {"x", "y"}


def test_recheck_drops_out_of_scope_user_memory() -> None:
    mine = uuid.uuid4()
    other = uuid.uuid4()
    org_id = uuid.uuid4()
    sf = ScopeFilter(user_id=mine, include_org=True, include_shared=False)
    keep = _rec("keep", org_id=org_id, scope="user", scope_ref_id=mine, visibility="private")
    drop = _rec("drop", org_id=org_id, scope="user", scope_ref_id=other, visibility="private")
    org = _rec("org", org_id=org_id, scope="org", visibility="private")
    out = _recheck_scope([keep, drop, org], sf)
    ids = {r.id for r in out}
    assert "keep" in ids
    assert "org" in ids
    assert "drop" not in ids


def test_recheck_passes_pillar_records_without_scope() -> None:
    sf = ScopeFilter()
    proc = _rec("p", pillar="procedural")
    out = _recheck_scope([proc], sf)
    assert len(out) == 1


async def test_search_passes_pillar_to_keyword_search() -> None:
    org_id = uuid.uuid4()
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.keyword_search = AsyncMock(return_value=[])
    audit = MagicMock()
    audit.record = AsyncMock()
    retrieval = SecureRetrieval(
        vector_store=vector_store,
        audit=audit,
        strategic=MagicMock(),
        work=MagicMock(),
    )
    ctx = SimpleNamespace(
        org_id=org_id,
        principal=SimpleNamespace(
            attribution="cursor",
            type="agent",
            id=uuid.uuid4(),
        ),
        authorizer=SimpleNamespace(require=AsyncMock()),
        accessible_scope_filter=AsyncMock(return_value=ScopeFilter(include_org=True)),
        request_id="req-2",
    )

    await retrieval.search(ctx, "episodic only", scopes=("episodic",))

    kw_kwargs = vector_store.keyword_search.await_args.kwargs
    assert kw_kwargs["pillar"] == "episodic"
    assert kw_kwargs["time_range"] is None


async def test_search_audits_privacy_safe_cross_agent_metrics() -> None:
    org_id = uuid.uuid4()
    vector_store = MagicMock()
    vector_store.search = AsyncMock(
        return_value=[_rec("shared", agent="hermes", org_id=org_id)]
    )
    vector_store.keyword_search = AsyncMock(return_value=[])
    audit = MagicMock()
    audit.record = AsyncMock()
    retrieval = SecureRetrieval(
        vector_store=vector_store,
        audit=audit,
        strategic=MagicMock(),
        work=MagicMock(),
    )
    ctx = SimpleNamespace(
        org_id=org_id,
        principal=SimpleNamespace(
            attribution="cursor",
            type="agent",
            id=uuid.uuid4(),
        ),
        authorizer=SimpleNamespace(require=AsyncMock()),
        accessible_scope_filter=AsyncMock(return_value=ScopeFilter(include_org=True)),
        request_id="req-1",
    )

    result = await retrieval.search(ctx, "private query text", scopes=("semantic",))

    assert len(result.records) == 1
    payload = audit.record.await_args.kwargs["payload"]
    assert "query" not in payload
    assert payload["query_length"] == len("private query text")
    assert payload["returned"] == 1
    assert payload["distinct_writers"] == 1
    assert payload["cross_agent_returned"] is True
    assert payload["latency_ms"] >= 0
