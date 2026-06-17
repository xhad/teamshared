"""Org-scoped persistence for workflow runs and their per-item step history.

``WorkflowRunStore`` is the authoritative state for a procedural loop. Every
statement runs inside ``db.org(org_id)`` so RLS isolates runs per tenant,
mirroring :class:`teamshared.agents.runs.AgentRunStore`. The orchestrator owns
the routing/loop logic; this store only does CRUD plus a couple of focused
aggregate queries it needs to decide when a run is complete.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

WorkflowRunStatus = Literal["running", "paused", "completed", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "waiting_human", "done", "failed", "skipped"]

_RUN_TERMINAL: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
_STEP_TERMINAL: frozenset[str] = frozenset({"done", "failed", "skipped"})

_RUN_FIELDS = (
    "id", "org_id", "workflow_name", "workflow_version",
    "status", "iteration", "max_iterations",
    "selector_json", "initiative_id", "project_id", "error",
    "created_by", "created_at", "updated_at", "completed_at",
)
_RUN_SELECT = ", ".join(_RUN_FIELDS)
_RUN_MARK_ALLOWED: frozenset[str] = frozenset(
    {"workflow_version", "iteration", "max_iterations", "error"}
)

_STEP_FIELDS = (
    "id", "org_id", "workflow_run_id", "work_item_id",
    "stage_id", "owner", "status", "seq",
    "agent_run_id", "note", "created_at", "started_at", "completed_at",
)
_STEP_SELECT = ", ".join(_STEP_FIELDS)
_STEP_MARK_ALLOWED: frozenset[str] = frozenset({"agent_run_id", "note"})


class WorkflowRunStore:
    """CRUD over ``workflow_runs`` / ``workflow_step_runs`` (RLS-enforced)."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    # -- runs --------------------------------------------------------------

    async def create_run(
        self,
        org_id: UUID,
        *,
        workflow_name: str,
        created_by: str,
        workflow_version: int | None = None,
        selector: dict[str, Any] | None = None,
        initiative_id: UUID | None = None,
        project_id: UUID | None = None,
        max_iterations: int = 10,
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                INSERT INTO workflow_runs (
                    org_id, workflow_name, workflow_version,
                    selector_json, initiative_id, project_id, max_iterations,
                    created_by
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                RETURNING {_RUN_SELECT}
                """,
                (
                    str(org_id), workflow_name, workflow_version,
                    json.dumps(selector or {}),
                    str(initiative_id) if initiative_id else None,
                    str(project_id) if project_id else None,
                    max_iterations, created_by,
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT workflow_runs did not return a row")
        return _run_row(row)

    async def get_run(self, org_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_RUN_SELECT} FROM workflow_runs WHERE id = %s",
                (str(run_id),),
            )
            row = await cur.fetchone()
        return _run_row(row) if row else None

    async def list_runs(
        self,
        org_id: UUID,
        *,
        status: WorkflowRunStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT {_RUN_SELECT} FROM workflow_runs
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()
        return [_run_row(r) for r in rows]

    async def mark_run(
        self,
        org_id: UUID,
        run_id: UUID,
        *,
        status: WorkflowRunStatus | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []
        now = datetime.now(UTC)
        if status is not None:
            updates.append("status = %s")
            params.append(status)
            if status in _RUN_TERMINAL:
                updates.append("completed_at = %s")
                params.append(now)
        for key, val in fields.items():
            if key not in _RUN_MARK_ALLOWED:
                continue
            updates.append(f"{key} = %s")
            params.append(val)
        updates.append("updated_at = %s")
        params.append(now)
        params.append(str(run_id))
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE workflow_runs SET {", ".join(updates)}
                WHERE id = %s
                RETURNING {_RUN_SELECT}
                """,
                tuple(params),
            )
            row = await cur.fetchone()
        return _run_row(row) if row else None

    async def bump_iteration(self, org_id: UUID, run_id: UUID) -> int:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                UPDATE workflow_runs
                SET iteration = iteration + 1, updated_at = now()
                WHERE id = %s
                RETURNING iteration
                """,
                (str(run_id),),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # -- steps -------------------------------------------------------------

    async def create_step(
        self,
        org_id: UUID,
        *,
        workflow_run_id: UUID,
        work_item_id: UUID,
        stage_id: str,
        owner: str,
        status: StepStatus = "pending",
        agent_run_id: UUID | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Append a step run, auto-assigning the next ``seq`` for re-entries."""
        now = datetime.now(UTC)
        started_at = now if status in ("running", "waiting_human") else None
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                INSERT INTO workflow_step_runs (
                    org_id, workflow_run_id, work_item_id, stage_id, owner,
                    status, seq, agent_run_id, note, started_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    COALESCE(
                        (SELECT MAX(seq) + 1 FROM workflow_step_runs
                         WHERE workflow_run_id = %s AND work_item_id = %s
                           AND stage_id = %s),
                        0
                    ),
                    %s, %s, %s
                )
                RETURNING {_STEP_SELECT}
                """,
                (
                    str(org_id), str(workflow_run_id), str(work_item_id),
                    stage_id, owner, status,
                    str(workflow_run_id), str(work_item_id), stage_id,
                    str(agent_run_id) if agent_run_id else None, note, started_at,
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT workflow_step_runs did not return a row")
        return _step_row(row)

    async def get_step(self, org_id: UUID, step_id: UUID) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_STEP_SELECT} FROM workflow_step_runs WHERE id = %s",
                (str(step_id),),
            )
            row = await cur.fetchone()
        return _step_row(row) if row else None

    async def step_for_agent_run(
        self, org_id: UUID, agent_run_id: UUID
    ) -> dict[str, Any] | None:
        """Find the (non-terminal) step a completed agent run belongs to."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT {_STEP_SELECT} FROM workflow_step_runs
                WHERE agent_run_id = %s
                ORDER BY seq DESC
                LIMIT 1
                """,
                (str(agent_run_id),),
            )
            row = await cur.fetchone()
        return _step_row(row) if row else None

    async def mark_step(
        self,
        org_id: UUID,
        step_id: UUID,
        *,
        status: StepStatus | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []
        now = datetime.now(UTC)
        if status is not None:
            updates.append("status = %s")
            params.append(status)
            if status in ("running", "waiting_human"):
                updates.append("started_at = COALESCE(started_at, %s)")
                params.append(now)
            if status in _STEP_TERMINAL:
                updates.append("completed_at = %s")
                params.append(now)
        for key, val in fields.items():
            if key not in _STEP_MARK_ALLOWED:
                continue
            updates.append(f"{key} = %s")
            params.append(str(val) if key == "agent_run_id" and val else val)
        if not updates:
            return await self.get_step(org_id, step_id)
        params.append(str(step_id))
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE workflow_step_runs SET {", ".join(updates)}
                WHERE id = %s
                RETURNING {_STEP_SELECT}
                """,
                tuple(params),
            )
            row = await cur.fetchone()
        return _step_row(row) if row else None

    async def list_steps_for_run(
        self, org_id: UUID, run_id: UUID
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT {_STEP_SELECT} FROM workflow_step_runs
                WHERE workflow_run_id = %s
                ORDER BY created_at ASC, seq ASC
                """,
                (str(run_id),),
            )
            rows = await cur.fetchall()
        return [_step_row(r) for r in rows]

    async def list_steps_for_work(
        self, org_id: UUID, work_id: UUID
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT {_STEP_SELECT} FROM workflow_step_runs
                WHERE work_item_id = %s
                ORDER BY created_at ASC, seq ASC
                """,
                (str(work_id),),
            )
            rows = await cur.fetchall()
        return [_step_row(r) for r in rows]

    async def run_item_ids(self, org_id: UUID, run_id: UUID) -> list[UUID]:
        """Distinct work items that have entered this run."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT DISTINCT work_item_id FROM workflow_step_runs "
                "WHERE workflow_run_id = %s",
                (str(run_id),),
            )
            rows = await cur.fetchall()
        return [UUID(str(r[0])) for r in rows]

    async def has_open_steps(self, org_id: UUID, run_id: UUID) -> bool:
        """True while any step is still pending/running/waiting on a human."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT 1 FROM workflow_step_runs
                WHERE workflow_run_id = %s
                  AND status IN ('pending', 'running', 'waiting_human')
                LIMIT 1
                """,
                (str(run_id),),
            )
            row = await cur.fetchone()
        return row is not None

    # -- work-item pointers ------------------------------------------------

    async def set_work_pointer(
        self,
        org_id: UUID,
        work_id: UUID,
        *,
        run_id: UUID | None,
        stage: str | None,
    ) -> None:
        """Denormalize the current workflow position onto the work item.

        Kept out of :class:`WorkStore.update` so the ``work_update`` tool surface
        stays free of workflow internals.
        """
        async with self.db.org(org_id) as conn:
            await conn.execute(
                """
                UPDATE work_items
                SET workflow_run_id = %s, current_stage = %s, updated_at = now()
                WHERE id = %s
                """,
                (str(run_id) if run_id else None, stage, str(work_id)),
            )


def _run_row(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(zip(_RUN_FIELDS, row, strict=False))


def _step_row(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(zip(_STEP_FIELDS, row, strict=False))
