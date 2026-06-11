"""HnswCache: hydration, org isolation, write-through, and VectorStore wiring."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from teamshared.memory.embeddings import HashEmbedder
from teamshared.memory.hnsw_cache import HnswCache, parse_vector_text
from teamshared.memory.vectorstore import ScopeFilter, VectorStore

pytest.importorskip("hnswlib")

DIMS = 8


def _vec(*hot: int) -> list[float]:
    v = [0.0] * DIMS
    for h in hot:
        v[h] = 1.0
    return v


def _vec_text(vec: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class FakeConn:
    """Captures executed SQL; returns canned rows."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []
        self.queries: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.queries.append((sql, params))
        return FakeCursor(self.rows)


class FakeDb:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.org_ids: list[str] = []

    @asynccontextmanager
    async def org(self, org_id: Any):
        self.org_ids.append(str(org_id))
        yield self.conn


def test_parse_vector_text_roundtrip() -> None:
    assert parse_vector_text("[0.5,-1.0,0]") == [0.5, -1.0, 0.0]
    assert parse_vector_text("[]") == []


async def test_hydrate_and_search_returns_nearest() -> None:
    cache = HnswCache(DIMS)
    org = str(uuid.uuid4())
    db = FakeDb(FakeConn(rows=[("m1", _vec_text(_vec(0))), ("m2", _vec_text(_vec(1)))]))
    await cache.ensure_hydrated(org, db, "hash")  # type: ignore[arg-type]
    assert cache.is_hydrated(org)
    hits = cache.search(org, _vec(0), k=2)
    assert hits is not None
    assert hits[0][0] == "m1"
    assert hits[0][1] == pytest.approx(0.0, abs=1e-5)


async def test_org_isolation() -> None:
    cache = HnswCache(DIMS)
    org_a, org_b = str(uuid.uuid4()), str(uuid.uuid4())
    await cache.ensure_hydrated(org_a, FakeDb(FakeConn(rows=[("a1", _vec_text(_vec(0)))])), "hash")  # type: ignore[arg-type]
    await cache.ensure_hydrated(org_b, FakeDb(FakeConn(rows=[("b1", _vec_text(_vec(0)))])), "hash")  # type: ignore[arg-type]
    hits_a = cache.search(org_a, _vec(0), k=10)
    assert hits_a is not None
    assert {mid for mid, _ in hits_a} == {"a1"}
    hits_b = cache.search(org_b, _vec(0), k=10)
    assert hits_b is not None
    assert {mid for mid, _ in hits_b} == {"b1"}


async def test_write_through_add_remove_invalidate() -> None:
    cache = HnswCache(DIMS)
    org = str(uuid.uuid4())
    await cache.ensure_hydrated(org, FakeDb(FakeConn(rows=[])), "hash")  # type: ignore[arg-type]

    # Add before hydration of another org is a no-op (no index yet).
    cache.add("other-org", "x", _vec(0))
    assert cache.search("other-org", _vec(0), k=1) is None

    cache.add(org, "m1", _vec(2))
    hits = cache.search(org, _vec(2), k=1)
    assert hits is not None and hits[0][0] == "m1"

    # Replacing the same memory id keeps a single entry.
    cache.add(org, "m1", _vec(3))
    hits = cache.search(org, _vec(3), k=5)
    assert hits is not None and [m for m, _ in hits] == ["m1"]

    cache.remove(org, "m1")
    assert cache.search(org, _vec(3), k=1) == []

    cache.invalidate(org)
    assert not cache.is_hydrated(org)
    assert cache.search(org, _vec(3), k=1) is None


async def test_model_change_triggers_rehydration() -> None:
    cache = HnswCache(DIMS)
    org = str(uuid.uuid4())
    await cache.ensure_hydrated(org, FakeDb(FakeConn(rows=[("old", _vec_text(_vec(0)))])), "model-a")  # type: ignore[arg-type]
    await cache.ensure_hydrated(org, FakeDb(FakeConn(rows=[("new", _vec_text(_vec(0)))])), "model-b")  # type: ignore[arg-type]
    hits = cache.search(org, _vec(0), k=5)
    assert hits is not None
    assert {mid for mid, _ in hits} == {"new"}


def test_disabled_cache_is_unavailable() -> None:
    cache = HnswCache(DIMS, enabled=False)
    assert not cache.available
    assert cache.search("org", _vec(0), k=1) is None


def _item_row(memory_id: str) -> tuple[Any, ...]:
    # Shape of the candidate-hydration SELECT in VectorStore._search_from_candidates.
    return (
        memory_id, "semantic", "fact", "content", None, [],
        "org", None, "private", "manual", None,
        None, 1, "active", datetime.now(UTC), "cursor",
        None,
    )


async def test_vectorstore_search_uses_cache_candidates() -> None:
    org_id = uuid.uuid4()
    mid = str(uuid.uuid4())
    embedder = HashEmbedder(DIMS)
    cache = HnswCache(DIMS)
    conn = FakeConn(rows=[_item_row(mid)])
    db = FakeDb(conn)
    store = VectorStore(db, embedder, cache=cache)  # type: ignore[arg-type]

    # Hydrate the org with the exact vector the query will produce.
    hydration_conn = FakeConn(rows=[(mid, _vec_text((await embedder.embed(["hello"]))[0]))])
    await cache.ensure_hydrated(str(org_id), FakeDb(hydration_conn), "hash")  # type: ignore[arg-type]

    records = await store.search(
        org_id=org_id, query="hello", scope_filter=ScopeFilter(), k=3
    )
    assert [r.id for r in records] == [mid]
    assert records[0].score == pytest.approx(1.0, abs=1e-4)
    sql, params = conn.queries[-1]
    assert "mi.id = ANY(%s)" in sql
    assert mid in params[0]
    # Scope filter still applied in SQL even on the cache path.
    assert "mi.scope = 'org'" in sql


async def test_vectorstore_falls_back_to_pgvector_on_cache_failure() -> None:
    class BrokenCache:
        available = True

        async def ensure_hydrated(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("boom")

    org_id = uuid.uuid4()
    conn = FakeConn(rows=[])
    store = VectorStore(FakeDb(conn), HashEmbedder(DIMS), cache=BrokenCache())  # type: ignore[arg-type]
    records = await store.search(
        org_id=org_id, query="hello", scope_filter=ScopeFilter(), k=3
    )
    assert records == []
    sql, params = conn.queries[-1]
    assert "me.embedding <=>" in sql
    # SQL path pins distances to the active embedder model.
    assert "me.model = %s" in sql
    assert "hash" in params


async def test_vectorstore_sql_path_filters_by_model_when_no_cache() -> None:
    conn = FakeConn(rows=[])
    store = VectorStore(FakeDb(conn), HashEmbedder(DIMS))  # type: ignore[arg-type]
    await store.search(
        org_id=uuid.uuid4(), query="q", scope_filter=ScopeFilter(), k=2
    )
    sql, params = conn.queries[-1]
    assert "me.model = %s" in sql
    assert params[1] == "hash"  # params[0] is the query vector literal
