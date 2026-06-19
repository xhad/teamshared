"""Retrieval pipeline pure-logic tests: rerank, RRF merge, and scope recheck."""

from __future__ import annotations

import uuid

from teamshared.memory.hybrid import reciprocal_rank_fusion
from teamshared.memory.retrieval import _recheck_scope, _rerank
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
