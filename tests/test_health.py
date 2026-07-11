"""Direct tests for the shared health probe (``check_components``).

The /health body is what operators (and the Docker healthcheck) trust, so the
degraded paths are pinned here: dependency errors, missing worker heartbeats,
queue alerts, and the optional-component rules (``disabled`` is healthy,
``down`` is not).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis

from teamshared.config import Settings
from teamshared.memory.working import (
    DISTILL_DEAD_LETTER_KEY,
    DISTILL_QUEUE_KEY,
    WorkingMemory,
)
from teamshared.server.health import _is_healthy, check_components


def _make_state(
    *,
    settings: Settings | None = None,
    working: WorkingMemory | None = None,
    postgres_ok: bool = True,
    graph: Any | None = None,
) -> SimpleNamespace:
    settings = settings or Settings(_env_file=None)
    if working is None:
        working = WorkingMemory("redis://unused", default_ttl=3600)
        working._client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    @asynccontextmanager
    async def _admin() -> Any:
        if not postgres_ok:
            raise RuntimeError("connection refused")
        cur = MagicMock()
        cur.fetchone = AsyncMock(return_value=(1,))
        conn = MagicMock()
        conn.execute = AsyncMock(return_value=cur)
        yield conn

    tenant_db = MagicMock()
    tenant_db.admin = _admin
    vector_store = MagicMock()
    vector_store.health = AsyncMock(return_value="hash-embedder")
    services = SimpleNamespace(tenant_db=tenant_db, vector_store=vector_store)
    return SimpleNamespace(
        settings=settings, working=working, services=services, graph=graph
    )


async def _beat(working: WorkingMemory, *names: str) -> None:
    for name in names:
        await working.heartbeat(name, ttl=60)


def test_is_healthy_rules() -> None:
    assert _is_healthy("ok")
    assert _is_healthy("ok (gpt-4o-mini)")
    assert _is_healthy("disabled")
    assert _is_healthy("warning")
    assert not _is_healthy("down")
    assert not _is_healthy("degraded")
    assert not _is_healthy("error: boom")


async def test_all_components_ok() -> None:
    state = _make_state(graph=SimpleNamespace(verify=AsyncMock()))
    await _beat(state.working, "distiller", "curator")
    body = await check_components(state)
    assert body["status"] == "ok"
    components = body["components"]
    assert components["server"] == "ok"
    assert components["redis"] == "ok"
    assert components["postgres"] == "ok"
    assert components["semantic"] == "ok (hash-embedder)"
    assert components["distiller"] == "ok"
    assert components["curator"] == "ok"
    assert components["graph"] == "ok"
    assert components["provider"] == "ok (openai)"  # openai is the default backend
    assert components["queues"] == "ok"


async def test_missing_worker_heartbeats_degrade() -> None:
    state = _make_state(graph=SimpleNamespace(verify=AsyncMock()))
    body = await check_components(state)
    assert body["components"]["distiller"] == "down"
    assert body["components"]["curator"] == "down"
    assert body["status"] == "degraded"


async def test_postgres_error_degrades_with_detail() -> None:
    state = _make_state(postgres_ok=False, graph=SimpleNamespace(verify=AsyncMock()))
    await _beat(state.working, "distiller", "curator")
    body = await check_components(state)
    assert body["components"]["postgres"].startswith("error: connection refused")
    assert body["status"] == "degraded"


async def test_graph_none_reports_disabled_and_does_not_degrade() -> None:
    state = _make_state(graph=None)
    await _beat(state.working, "distiller", "curator")
    body = await check_components(state)
    assert body["components"]["graph"] == "disabled"
    assert body["status"] == "ok"


async def test_graph_verify_failure_reports_error() -> None:
    graph = SimpleNamespace(verify=AsyncMock(side_effect=RuntimeError("neo4j gone")))
    state = _make_state(graph=graph)
    await _beat(state.working, "distiller", "curator")
    body = await check_components(state)
    assert body["components"]["graph"] == "error: neo4j gone"
    assert body["status"] == "degraded"


async def test_queue_warning_does_not_degrade() -> None:
    settings = Settings(
        _env_file=None,
        queue_depth_warn_threshold=2,
        queue_depth_critical_threshold=100,
    )
    state = _make_state(settings=settings, graph=SimpleNamespace(verify=AsyncMock()))
    await _beat(state.working, "distiller", "curator")
    await state.working.client.rpush(DISTILL_QUEUE_KEY, "j1", "j2", "j3")
    body = await check_components(state)
    assert body["components"]["queues"] == "warning"
    assert body["status"] == "ok"
    assert body["queues"]["distill_queue"] == 3


async def test_dead_letter_degrades_via_queues() -> None:
    state = _make_state(graph=SimpleNamespace(verify=AsyncMock()))
    await _beat(state.working, "distiller", "curator")
    await state.working.client.rpush(DISTILL_DEAD_LETTER_KEY, "dead")
    body = await check_components(state)
    assert body["components"]["queues"] == "degraded"
    assert body["status"] == "degraded"


async def test_redis_error_reported() -> None:
    state = _make_state(graph=SimpleNamespace(verify=AsyncMock()))
    state.working.client.ping = AsyncMock(side_effect=RuntimeError("redis down"))
    body = await check_components(state)
    assert body["components"]["redis"] == "error: redis down"
    assert body["status"] == "degraded"
