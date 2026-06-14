"""Agent-run store: leasing, idempotency, traces, and RLS (integration).

Run with: ``pytest -m integration`` against the compose Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from teamshared.agents.runs import AgentRunStore
from teamshared.config import get_settings
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository


async def _seed_work(db: TenantDb, org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an agent + a work item under ``org_id``; return (agent_id, work_id)."""
    async with db.org(org_id) as conn:
        cur = await conn.execute(
            "INSERT INTO agents (org_id, name) VALUES (%s, %s) RETURNING id",
            (str(org_id), f"worker-{uuid.uuid4().hex[:6]}"),
        )
        agent_id = (await cur.fetchone())[0]
        cur = await conn.execute(
            "INSERT INTO work_items (org_id, title, created_by) "
            "VALUES (%s, %s, %s) RETURNING id",
            (str(org_id), "Async task", "tester"),
        )
        work_id = (await cur.fetchone())[0]
    return agent_id, work_id


@pytest.mark.integration
async def test_lease_is_single_owner_and_reclaimable() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = AgentRunStore(db)
    try:
        org = await repo.create_organization(f"runs-{uuid.uuid4().hex[:8]}", "Runs Org")
        agent_id, work_id = await _seed_work(db, org.id)

        run = await store.create(
            org.id, work_item_id=work_id, agent_id=agent_id, created_by="tester",
        )
        run_id = uuid.UUID(str(run["id"]))
        assert run["status"] == "queued"

        # First worker claims it.
        leased = await store.lease(org.id, run_id, owner="w1", ttl_seconds=300)
        assert leased is not None
        assert leased["status"] == "running"
        assert leased["lease_owner"] == "w1"

        # A duplicate delivery to a second worker is a no-op (exactly-once).
        again = await store.lease(org.id, run_id, owner="w2", ttl_seconds=300)
        assert again is None

        # Crash recovery: once the lease expires, another worker can reclaim it.
        await store.mark(
            org.id, run_id,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        reclaimed = await store.lease(org.id, run_id, owner="w2", ttl_seconds=300)
        assert reclaimed is not None
        assert reclaimed["lease_owner"] == "w2"
        assert reclaimed["attempt"] == 2
    finally:
        await db.close()


@pytest.mark.integration
async def test_terminal_run_cannot_be_leased() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = AgentRunStore(db)
    try:
        org = await repo.create_organization(f"runs-{uuid.uuid4().hex[:8]}", "Runs Org")
        agent_id, work_id = await _seed_work(db, org.id)
        run = await store.create(
            org.id, work_item_id=work_id, agent_id=agent_id, created_by="tester",
        )
        run_id = uuid.UUID(str(run["id"]))
        await store.mark(org.id, run_id, status="completed")
        assert await store.lease(org.id, run_id, owner="w1", ttl_seconds=60) is None
    finally:
        await db.close()


@pytest.mark.integration
async def test_trace_sequence_and_model_calls() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = AgentRunStore(db)
    try:
        org = await repo.create_organization(f"runs-{uuid.uuid4().hex[:8]}", "Runs Org")
        agent_id, work_id = await _seed_work(db, org.id)
        run = await store.create(
            org.id, work_item_id=work_id, agent_id=agent_id, created_by="tester",
        )
        run_id = uuid.UUID(str(run["id"]))

        await store.append_trace(org.id, run_id, event_type="started", summary="a")
        await store.append_trace(org.id, run_id, event_type="model_call", summary="b")
        trace = await store.list_trace(org.id, run_id)
        assert [t["sequence"] for t in trace] == [0, 1]

        await store.record_model_call(
            org.id, run_id, model="m", provider="openrouter",
            prompt_tokens=10, completion_tokens=2, latency_ms=42,
        )
        calls = await store.list_model_calls(org.id, run_id)
        assert calls and calls[0]["latency_ms"] == 42
    finally:
        await db.close()


@pytest.mark.integration
async def test_runs_isolated_across_orgs() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = AgentRunStore(db)
    try:
        org_a = await repo.create_organization(f"a-{uuid.uuid4().hex[:8]}", "A")
        org_b = await repo.create_organization(f"b-{uuid.uuid4().hex[:8]}", "B")
        agent_id, work_id = await _seed_work(db, org_a.id)
        run = await store.create(
            org_a.id, work_item_id=work_id, agent_id=agent_id, created_by="tester",
        )
        run_id = uuid.UUID(str(run["id"]))

        # Org B cannot see org A's run (RLS fails closed).
        assert await store.get(org_b.id, run_id) is None
        assert await store.list_for_org(org_b.id) == []
        # Org A still sees it.
        assert await store.get(org_a.id, run_id) is not None
    finally:
        await db.close()
