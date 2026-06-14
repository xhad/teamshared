"""Org-scoped persistence for background agent runs and their traces.

``AgentRunStore`` is the authoritative state machine for a run. The Redis stream
is only a delivery hint; correctness comes from the row's ``status`` plus the
lease (``lease_owner`` / ``lease_expires_at``). :meth:`lease` is the single
critical section: it atomically claims a ``queued`` run (or reclaims a
``running`` one whose lease expired after a worker crash) so two workers can
never execute the same run.

Every statement runs inside ``db.org(org_id)`` so RLS isolates runs per tenant.
``agent_model_calls`` and trace payloads store only redacted metadata + short
summaries -- never raw prompts, responses, secrets, or credentials.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

AgentRunStatus = Literal[
    "queued", "running", "completed", "failed", "paused", "cancelled"
]

_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

_RUN_FIELDS = (
    "id", "org_id", "work_item_id", "agent_id",
    "playbook_name", "playbook_version",
    "status", "cancel_requested",
    "model", "provider", "request_id",
    "prompt_tokens", "completion_tokens", "latency_ms", "error",
    "attempt", "lease_owner", "lease_expires_at",
    "started_at", "completed_at", "created_by", "created_at", "updated_at",
)
_RUN_SELECT = ", ".join(_RUN_FIELDS)

_MARK_ALLOWED: frozenset[str] = frozenset(
    {
        "model", "provider", "request_id",
        "prompt_tokens", "completion_tokens", "latency_ms", "error",
        "playbook_name", "playbook_version", "cancel_requested",
        "lease_owner", "lease_expires_at", "attempt",
        "started_at", "completed_at",
    }
)


class AgentRunStore:
    """CRUD + lease over ``agent_runs`` and its trace tables (RLS-enforced)."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def create(
        self,
        org_id: UUID,
        *,
        work_item_id: UUID,
        agent_id: UUID,
        created_by: str,
        playbook_name: str | None = None,
        playbook_version: int | None = None,
        model: str | None = None,
        provider: str | None = None,
        status: AgentRunStatus = "queued",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                INSERT INTO agent_runs (
                    org_id, work_item_id, agent_id,
                    playbook_name, playbook_version,
                    status, model, provider, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_RUN_SELECT}
                """,
                (
                    str(org_id), str(work_item_id), str(agent_id),
                    playbook_name, playbook_version,
                    status, model, provider, created_by,
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT agent_runs did not return a row")
        return _run_row(row)

    async def get(self, org_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_RUN_SELECT} FROM agent_runs WHERE id = %s",
                (str(run_id),),
            )
            row = await cur.fetchone()
        return _run_row(row) if row else None

    async def list_for_org(
        self,
        org_id: UUID,
        *,
        status: AgentRunStatus | None = None,
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
                SELECT {_RUN_SELECT} FROM agent_runs
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()
        runs = [_run_row(r) for r in rows]
        await self.enrich(org_id, runs)
        return runs

    async def list_for_work(
        self, org_id: UUID, work_id: UUID, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT {_RUN_SELECT} FROM agent_runs
                WHERE work_item_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (str(work_id), limit),
            )
            rows = await cur.fetchall()
        runs = [_run_row(r) for r in rows]
        await self.enrich(org_id, runs)
        return runs

    async def latest_for_work(
        self, org_id: UUID, work_id: UUID
    ) -> dict[str, Any] | None:
        runs = await self.list_for_work(org_id, work_id, limit=1)
        return runs[0] if runs else None

    async def lease(
        self, org_id: UUID, run_id: UUID, *, owner: str, ttl_seconds: int
    ) -> dict[str, Any] | None:
        """Atomically claim a run for execution. Returns the row or ``None``.

        Succeeds only when the run is ``queued`` or is a ``running`` run whose
        lease already expired (crash recovery). Any other state -- already
        owned, completed, failed, cancelled -- returns ``None`` so the caller
        acks and skips, which is what keeps execution exactly-once.
        """
        now = datetime.now(UTC)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE agent_runs
                SET status = 'running',
                    lease_owner = %s,
                    lease_expires_at = %s + make_interval(secs => %s),
                    attempt = attempt + 1,
                    started_at = COALESCE(started_at, %s),
                    updated_at = %s
                WHERE id = %s
                  AND (
                    status = 'queued'
                    OR (status = 'running' AND lease_expires_at < %s)
                  )
                RETURNING {_RUN_SELECT}
                """,
                (
                    owner, now, float(ttl_seconds), now, now,
                    str(run_id), now,
                ),
            )
            row = await cur.fetchone()
        return _run_row(row) if row else None

    async def renew_lease(
        self, org_id: UUID, run_id: UUID, *, owner: str, ttl_seconds: int
    ) -> bool:
        """Extend a held lease mid-run. False if the lease was lost/cancelled."""
        now = datetime.now(UTC)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                UPDATE agent_runs
                SET lease_expires_at = %s + make_interval(secs => %s), updated_at = %s
                WHERE id = %s AND lease_owner = %s AND status = 'running'
                """,
                (now, float(ttl_seconds), now, str(run_id), owner),
            )
            return cur.rowcount > 0

    async def mark(
        self,
        org_id: UUID,
        run_id: UUID,
        *,
        status: AgentRunStatus | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """Update a run's status and/or metadata fields.

        Setting ``status='running'`` stamps ``started_at`` (if unset); a terminal
        status stamps ``completed_at`` and clears the lease.
        """
        updates: list[str] = []
        params: list[Any] = []
        now = datetime.now(UTC)
        if status is not None:
            updates.append("status = %s")
            params.append(status)
            if status == "running":
                updates.append("started_at = COALESCE(started_at, %s)")
                params.append(now)
            if status in _TERMINAL_STATUSES:
                updates.append("completed_at = %s")
                params.append(now)
                updates.append("lease_owner = NULL")
                updates.append("lease_expires_at = NULL")
        for key, val in fields.items():
            if key not in _MARK_ALLOWED:
                continue
            updates.append(f"{key} = %s")
            params.append(val)
        updates.append("updated_at = %s")
        params.append(now)
        params.append(str(run_id))
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE agent_runs SET {", ".join(updates)}
                WHERE id = %s
                RETURNING {_RUN_SELECT}
                """,
                tuple(params),
            )
            row = await cur.fetchone()
        return _run_row(row) if row else None

    async def request_cancel(
        self, org_id: UUID, run_id: UUID
    ) -> dict[str, Any] | None:
        """Flag a run for cancellation.

        A ``queued`` run is cancelled immediately; a ``running`` run gets a
        ``cancel_requested`` flag the worker checks at its next safe point.
        Terminal runs are returned unchanged.
        """
        now = datetime.now(UTC)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE agent_runs
                SET cancel_requested = TRUE,
                    status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                    completed_at = CASE WHEN status = 'queued' THEN %s ELSE completed_at END,
                    updated_at = %s
                WHERE id = %s
                RETURNING {_RUN_SELECT}
                """,
                (now, now, str(run_id)),
            )
            row = await cur.fetchone()
        return _run_row(row) if row else None

    async def is_cancel_requested(self, org_id: UUID, run_id: UUID) -> bool:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT cancel_requested, status FROM agent_runs WHERE id = %s",
                (str(run_id),),
            )
            row = await cur.fetchone()
        if row is None:
            return False
        return bool(row[0]) or row[1] == "cancelled"

    # -- trace events ------------------------------------------------------

    async def append_trace(
        self,
        org_id: UUID,
        run_id: UUID,
        *,
        event_type: str,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload_json = json.dumps(payload or {})
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO agent_trace_events
                    (org_id, run_id, event_type, sequence, summary, payload_json)
                VALUES (
                    %s, %s, %s,
                    COALESCE(
                        (SELECT MAX(sequence) + 1 FROM agent_trace_events WHERE run_id = %s),
                        0
                    ),
                    %s, %s::jsonb
                )
                RETURNING id, run_id, event_type, sequence, summary, payload_json, created_at
                """,
                (
                    str(org_id), str(run_id), event_type, str(run_id),
                    summary, payload_json,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        return _trace_row(row)

    async def list_trace(
        self, org_id: UUID, run_id: UUID, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, run_id, event_type, sequence, summary, payload_json, created_at
                FROM agent_trace_events
                WHERE run_id = %s
                ORDER BY sequence ASC
                LIMIT %s
                """,
                (str(run_id), limit),
            )
            rows = await cur.fetchall()
        return [_trace_row(r) for r in rows]

    # -- model calls -------------------------------------------------------

    async def record_model_call(
        self,
        org_id: UUID,
        run_id: UUID,
        *,
        model: str | None,
        provider: str | None,
        request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO agent_model_calls
                    (org_id, run_id, model, provider, request_id,
                     prompt_tokens, completion_tokens, latency_ms, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, run_id, model, provider, request_id,
                          prompt_tokens, completion_tokens, latency_ms, error, created_at
                """,
                (
                    str(org_id), str(run_id), model, provider, request_id,
                    prompt_tokens, completion_tokens, latency_ms, error,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        return _model_call_row(row)

    async def list_model_calls(
        self, org_id: UUID, run_id: UUID
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, run_id, model, provider, request_id,
                       prompt_tokens, completion_tokens, latency_ms, error, created_at
                FROM agent_model_calls
                WHERE run_id = %s
                ORDER BY created_at ASC
                """,
                (str(run_id),),
            )
            rows = await cur.fetchall()
        return [_model_call_row(r) for r in rows]

    # -- enrichment --------------------------------------------------------

    async def enrich(self, org_id: UUID, runs: list[dict[str, Any]]) -> None:
        """Attach human-readable ``agent_name`` + ``work_title`` in-place."""
        if not runs:
            return
        agent_ids = {str(r["agent_id"]) for r in runs if r.get("agent_id")}
        work_ids = {str(r["work_item_id"]) for r in runs if r.get("work_item_id")}
        agent_names: dict[str, str] = {}
        work_titles: dict[str, str] = {}
        async with self.db.org(org_id) as conn:
            if agent_ids:
                cur = await conn.execute(
                    "SELECT id::text, name FROM agents WHERE id = ANY(%s::uuid[])",
                    (list(agent_ids),),
                )
                for arow in await cur.fetchall():
                    agent_names[arow[0]] = arow[1]
            if work_ids:
                cur = await conn.execute(
                    "SELECT id::text, title FROM work_items WHERE id = ANY(%s::uuid[])",
                    (list(work_ids),),
                )
                for wrow in await cur.fetchall():
                    work_titles[wrow[0]] = wrow[1]
        for r in runs:
            r["agent_name"] = agent_names.get(str(r.get("agent_id")))
            r["work_title"] = work_titles.get(str(r.get("work_item_id")))


def _run_row(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(zip(_RUN_FIELDS, row, strict=False))


def _trace_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "run_id": row[1],
        "event_type": row[2],
        "sequence": row[3],
        "summary": row[4],
        "payload_json": row[5] or {},
        "created_at": row[6],
    }


def _model_call_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "run_id": row[1],
        "model": row[2],
        "provider": row[3],
        "request_id": row[4],
        "prompt_tokens": row[5],
        "completion_tokens": row[6],
        "latency_ms": row[7],
        "error": row[8],
        "created_at": row[9],
    }
