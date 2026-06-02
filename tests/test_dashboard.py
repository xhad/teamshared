"""Memory status dashboard (`GET /memory`) and the store stats it renders."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.config import get_settings
from teamshared.memory.procedural import ProceduralStore
from teamshared.memory.semantic import SemanticEpisodicStore
from teamshared.memory.types import MemoryRecord
from teamshared.memory.working import (
    DISTILL_DEAD_LETTER_KEY,
    DISTILL_QUEUE_KEY,
    WorkingMemory,
)
from teamshared.server import dashboard
from teamshared.server.dashboard import handle_memory_dashboard


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeRedis:
    """Minimal async Redis stub for WorkingMemory.stats()."""

    def __init__(
        self,
        sessions: dict[str, dict[str, str]],
        turns: dict[str, int],
        queues: dict[str, int],
    ) -> None:
        self._sessions = sessions
        self._turns = turns
        self._queues = queues

    async def scan_iter(self, match: str | None = None, count: int | None = None):
        for key in list(self._sessions) + list(self._turns):
            yield key

    async def hgetall(self, key: str) -> dict[str, str]:
        return self._sessions.get(key, {})

    async def llen(self, key: str) -> int:
        if key in self._turns:
            return self._turns[key]
        return self._queues.get(key, 0)


class _FakeSyncCursor:
    def __init__(self, results: list[list[tuple]]) -> None:
        self._results = list(results)

    def __enter__(self) -> _FakeSyncCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, query: object, params: object = None) -> None:
        return None

    def fetchall(self) -> list[tuple]:
        return self._results.pop(0) if self._results else []


class _FakeSyncConn:
    def __init__(self, results: list[list[tuple]]) -> None:
        self._cursor = _FakeSyncCursor(results)

    def __enter__(self) -> _FakeSyncConn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def cursor(self) -> _FakeSyncCursor:
        return self._cursor


class _FakeAsyncCursor:
    def __init__(self, fetchone: list[tuple], fetchall: list[list[tuple]]) -> None:
        self._one = list(fetchone)
        self._all = list(fetchall)

    async def __aenter__(self) -> _FakeAsyncCursor:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, query: object, params: object = None) -> None:
        return None

    async def fetchone(self) -> tuple | None:
        return self._one.pop(0) if self._one else None

    async def fetchall(self) -> list[tuple]:
        return self._all.pop(0) if self._all else []


class _FakeAsyncConn:
    def __init__(self, cursor: _FakeAsyncCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _FakeAsyncConn:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def cursor(self) -> _FakeAsyncCursor:
        return self._cursor


class _FakeConnCM:
    def __init__(self, conn: _FakeAsyncConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeAsyncConn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self, cursor: _FakeAsyncCursor) -> None:
        self._cursor = cursor

    def connection(self) -> _FakeConnCM:
        return _FakeConnCM(_FakeAsyncConn(self._cursor))


# --------------------------------------------------------------------------- #
# Store stats unit tests
# --------------------------------------------------------------------------- #
ORG = "00000000-0000-0000-0000-000000000001"


def test_working_stats_aggregates_across_agents() -> None:
    sessions = {
        f"working:{ORG}:session:s1": {
            "agent": "cursor",
            "topic": "a",
            "opened_at": "2026-05-28T10:00:00",
            "closed_at": "",
        },
        f"working:{ORG}:session:s2": {
            "agent": "hermes",
            "topic": "b",
            "opened_at": "2026-05-28T09:00:00",
            "closed_at": "2026-05-28T11:00:00",
        },
    }
    turns = {f"working:{ORG}:session:s1:turns": 4, f"working:{ORG}:session:s2:turns": 7}
    queues = {DISTILL_QUEUE_KEY: 2, DISTILL_DEAD_LETTER_KEY: 1}

    wm = WorkingMemory("redis://unused", default_ttl=60)
    wm._client = _FakeRedis(sessions, turns, queues)  # type: ignore[assignment]

    stats = asyncio.run(wm.stats(ORG))

    assert stats["total"] == 2
    assert stats["active"] == 1
    assert stats["closed"] == 1
    assert stats["by_agent"] == {"cursor": 1, "hermes": 1}
    assert stats["distill_queue"] == 2
    assert stats["distill_dead"] == 1
    # Most recent opened_at first, with its turn count attached.
    assert stats["recent"][0]["session_id"] == "s1"
    assert stats["recent"][0]["turn_count"] == 4


def test_semantic_stats_and_list_recent(monkeypatch) -> None:
    store = SemanticEpisodicStore(get_settings())
    store._memory = object()  # mark ready without a real Mem0 client

    monkeypatch.setattr(
        "teamshared.memory.semantic.psycopg.connect",
        lambda dsn: _FakeSyncConn(
            [
                [("semantic", 5), ("episodic", 2)],
                [("cursor", 4), ("hermes", 3)],
                [("fact", 3), ("preference", 2)],
                [("test", 4), ("infra", 2)],
            ]
        ),
    )
    stats = asyncio.run(store.stats())
    assert stats["semantic"] == 5
    assert stats["episodic"] == 2
    assert stats["total"] == 7
    assert stats["by_agent"] == {"cursor": 4, "hermes": 3}
    assert stats["by_kind"] == {"fact": 3, "preference": 2}
    assert stats["tags"] == [("test", 4), ("infra", 2)]

    monkeypatch.setattr(
        "teamshared.memory.semantic.psycopg.connect",
        lambda dsn: _FakeSyncConn(
            [[("m1", "hello world", "cursor", "semantic", "fact", "2026-05-28T10:00:00+00:00")]]
        ),
    )
    records = asyncio.run(store.list_recent(limit=5, pillar="semantic"))
    assert len(records) == 1
    assert records[0].content == "hello world"
    assert records[0].agent == "cursor"
    assert records[0].pillar == "semantic"
    assert records[0].kind == "fact"


def test_semantic_stats_raises_when_not_ready() -> None:
    store = SemanticEpisodicStore(get_settings())  # _memory is None
    try:
        asyncio.run(store.stats())
    except RuntimeError as exc:
        assert "not ready" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError when mem0 is not ready")


def test_procedural_stats() -> None:
    cursor = _FakeAsyncCursor(
        fetchone=[(2, 3)],
        fetchall=[[("cursor", 3)], [("ci", 2)]],
    )
    store = ProceduralStore("postgresql://unused")
    store._pool = _FakePool(cursor)  # type: ignore[assignment]

    stats = asyncio.run(store.stats())
    assert stats["playbooks"] == 2
    assert stats["versions"] == 3
    assert stats["by_author"] == {"cursor": 3}
    assert stats["tags"] == [("ci", 2)]


# --------------------------------------------------------------------------- #
# Dashboard rendering tests
# --------------------------------------------------------------------------- #
def _working_stats() -> dict:
    return {
        "total": 3,
        "active": 2,
        "closed": 1,
        "by_agent": {"cursor": 2, "hermes": 1},
        "distill_queue": 1,
        "distill_dead": 0,
        "recent": [
            {
                "session_id": "sess_abc",
                "agent": "cursor",
                "topic": "<script>alert(1)</script>",
                "opened_at": "2026-05-28T10:00:00",
                "closed_at": "",
                "turn_count": 4,
            }
        ],
    }


def _semantic_stats() -> dict:
    return {
        "by_pillar": {"semantic": 5, "episodic": 2},
        "by_agent": {"cursor": 4, "hermes": 3},
        "by_kind": {"fact": 3, "preference": 2},
        "tags": [("test", 4), ("infra", 2)],
        "semantic": 5,
        "episodic": 2,
        "total": 7,
    }


def _semantic_records() -> list[MemoryRecord]:
    return [
        MemoryRecord(
            id="m1",
            pillar="semantic",
            kind="fact",
            content="<b>danger</b> & co",
            agent="cursor",
            created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
        )
    ]


def _make_state(*, semantic_ok: bool = True) -> SimpleNamespace:
    vector_store = SimpleNamespace(
        pillar_stats=AsyncMock(return_value=_semantic_stats()),
        list_recent=AsyncMock(return_value=_semantic_records()),
    )
    if not semantic_ok:
        vector_store.pillar_stats = AsyncMock(side_effect=RuntimeError("pgvector down"))
        vector_store.list_recent = AsyncMock(side_effect=RuntimeError("pgvector down"))
    procedural = SimpleNamespace(
        stats=AsyncMock(return_value={"playbooks": 2, "versions": 3, "by_author": {"cursor": 3}, "tags": [("ci", 2)]}),
        list_procedures=AsyncMock(
            return_value=[
                {
                    "name": "ship-pr",
                    "version": 2,
                    "created_by": "cursor",
                    "tags": ["ci"],
                    "created_at": datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
                }
            ]
        ),
    )
    working = SimpleNamespace(stats=AsyncMock(return_value=_working_stats()))
    return SimpleNamespace(
        settings=SimpleNamespace(
            default_org_id=ORG,
            dashboard_public_content=False,
        ),
        working=working,
        services=SimpleNamespace(vector_store=vector_store),
        procedural=procedural,
    )


def _client(state: SimpleNamespace) -> TestClient:
    async def route(request):
        return await handle_memory_dashboard(request, state)

    app = Starlette(routes=[Route("/memory", route, methods=["GET"])])
    return TestClient(app)


def test_dashboard_renders_and_escapes(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "check_components",
        AsyncMock(return_value={"status": "ok", "components": {"redis": "ok", "postgres": "ok", "mem0": "ok"}}),
    )
    resp = _client(_make_state()).get("/memory")
    assert resp.status_code == 200
    body = resp.text
    assert "teamshared memory status" in body
    for heading in ("Working sessions", "Semantic", "Episodic", "Procedural"):
        assert heading in body
    assert "cursor" in body
    assert "Recent activity" in body
    assert "TEAMSHARED_DASHBOARD_PUBLIC_CONTENT" in body
    # Public dashboard must not expose memory snippets by default.
    assert "ship-pr" not in body
    assert "&lt;b&gt;danger&lt;/b&gt;" not in body
    assert "<script>alert(1)</script>" not in body


def test_dashboard_shows_content_when_flag_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "check_components",
        AsyncMock(return_value={"status": "ok", "components": {"redis": "ok"}}),
    )
    state = _make_state()
    state.settings.dashboard_public_content = True
    body = _client(state).get("/memory").text
    assert "ship-pr" in body
    assert "&lt;b&gt;danger&lt;/b&gt; &amp; co" in body


def test_dashboard_degrades_when_store_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "check_components",
        AsyncMock(return_value={"status": "degraded", "components": {"redis": "ok", "postgres": "ok", "mem0": "not_ready"}}),
    )
    resp = _client(_make_state(semantic_ok=False)).get("/memory")
    assert resp.status_code == 200
    body = resp.text
    assert "unavailable" in body
    assert "Recent semantic" not in body
    assert "Recent activity" in body
