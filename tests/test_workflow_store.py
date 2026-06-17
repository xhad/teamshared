"""WorkflowRunStore: CRUD, step seq, pointers, and RLS (integration).

Run with: ``pytest -m integration`` against the compose Postgres.
"""

from __future__ import annotations

import uuid

import pytest

from teamshared.config import get_settings
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository
from teamshared.workflow.runs import WorkflowRunStore


async def _seed_work(db: TenantDb, org_id: uuid.UUID) -> uuid.UUID:
    async with db.org(org_id) as conn:
        cur = await conn.execute(
            "INSERT INTO work_items (org_id, title, created_by) "
            "VALUES (%s, %s, %s) RETURNING id",
            (str(org_id), "Loop task", "tester"),
        )
        return (await cur.fetchone())[0]


@pytest.mark.integration
async def test_run_and_step_lifecycle() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = WorkflowRunStore(db)
    try:
        org = await repo.create_organization(f"wf-{uuid.uuid4().hex[:8]}", "WF Org")
        work_id = await _seed_work(db, org.id)

        run = await store.create_run(
            org.id, workflow_name="ship", workflow_version=1, created_by="tester",
            selector={"work_status": "todo"}, max_iterations=3,
        )
        run_id = uuid.UUID(str(run["id"]))
        assert run["status"] == "running"
        assert run["selector_json"] == {"work_status": "todo"}

        # First step at a stage gets seq 0; a re-entry gets seq 1.
        s0 = await store.create_step(
            org.id, workflow_run_id=run_id, work_item_id=work_id,
            stage_id="build", owner="agent", status="running",
        )
        assert s0["seq"] == 0
        assert await store.has_open_steps(org.id, run_id) is True

        agent_run = uuid.uuid4()
        await store.mark_step(
            org.id, uuid.UUID(str(s0["id"])), agent_run_id=agent_run,
        )
        found = await store.step_for_agent_run(org.id, agent_run)
        assert found is not None
        assert str(found["id"]) == str(s0["id"])

        await store.mark_step(org.id, uuid.UUID(str(s0["id"])), status="done")
        s1 = await store.create_step(
            org.id, workflow_run_id=run_id, work_item_id=work_id,
            stage_id="build", owner="agent", status="running",
        )
        assert s1["seq"] == 1

        # Pointer denormalization onto the work item.
        await store.set_work_pointer(
            org.id, work_id, run_id=run_id, stage="build",
        )
        async with db.org(org.id) as conn:
            cur = await conn.execute(
                "SELECT workflow_run_id, current_stage FROM work_items WHERE id = %s",
                (str(work_id),),
            )
            row = await cur.fetchone()
        assert str(row[0]) == str(run_id)
        assert row[1] == "build"

        # Iteration bump + completion when no steps remain open.
        assert await store.bump_iteration(org.id, run_id) == 1
        await store.mark_step(org.id, uuid.UUID(str(s1["id"])), status="done")
        assert await store.has_open_steps(org.id, run_id) is False
        completed = await store.mark_run(org.id, run_id, status="completed")
        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None

        steps = await store.list_steps_for_run(org.id, run_id)
        assert len(steps) == 2
    finally:
        await db.close()


@pytest.mark.integration
async def test_rls_isolates_runs_across_orgs() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = WorkflowRunStore(db)
    try:
        org_a = await repo.create_organization(f"wf-a-{uuid.uuid4().hex[:8]}", "A")
        org_b = await repo.create_organization(f"wf-b-{uuid.uuid4().hex[:8]}", "B")
        run = await store.create_run(
            org_a.id, workflow_name="ship", created_by="tester",
        )
        run_id = uuid.UUID(str(run["id"]))
        # Org B cannot see org A's run.
        assert await store.get_run(org_b.id, run_id) is None
        assert await store.get_run(org_a.id, run_id) is not None
    finally:
        await db.close()
