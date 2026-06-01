"""Mandatory, tenant-scoped audit trail.

Every memory read/write/delete/share and every permission change records an
``audit_events`` row carrying ``org_id``, the actor (type + id), the resource,
optional before/after snapshots, and the originating request id. Writes are
transactional inside the org context (so RLS stamps the right tenant).

Read-path audit is best-effort (a logging hiccup must not fail a query); write,
delete, and share audit default to raising so an unrecorded mutation is a hard
error, not a silent gap.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.tenancy.context import TenantDb, current_org_id

log = get_logger(__name__)


class AuditLog:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def record(
        self,
        *,
        agent: str,
        action: str,
        org_id: UUID | None = None,
        actor_type: str | None = None,
        actor_id: UUID | None = None,
        resource_type: str | None = None,
        target_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        best_effort: bool = True,
    ) -> None:
        org = org_id or current_org_id()
        if org is None:
            msg = f"audit event {action!r} has no org context"
            if best_effort:
                log.warning("audit_missing_org", action=action)
                return
            raise RuntimeError(msg)
        try:
            async with self.db.org(org) as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_events
                        (org_id, agent, action, target_id, actor_type, actor_id,
                         resource_type, before, after, payload, request_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)
                    """,
                    (
                        str(org), agent, action, target_id, actor_type,
                        str(actor_id) if actor_id else None, resource_type,
                        json.dumps(before) if before is not None else None,
                        json.dumps(after) if after is not None else None,
                        json.dumps(payload or {}), request_id,
                    ),
                )
        except Exception as exc:
            if best_effort:
                log.warning("audit_record_failed", action=action, error=str(exc))
                return
            raise

    async def list_events(
        self, org_id: UUID, *, action: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            if action:
                cur = await conn.execute(
                    "SELECT occurred_at, agent, action, actor_type, actor_id, resource_type, "
                    "target_id, request_id, payload FROM audit_events "
                    "WHERE action = %s ORDER BY occurred_at DESC LIMIT %s",
                    (action, limit),
                )
            else:
                cur = await conn.execute(
                    "SELECT occurred_at, agent, action, actor_type, actor_id, resource_type, "
                    "target_id, request_id, payload FROM audit_events "
                    "ORDER BY occurred_at DESC LIMIT %s",
                    (limit,),
                )
            rows = await cur.fetchall()
        return [
            {
                "occurred_at": r[0].isoformat() if r[0] else None,
                "agent": r[1], "action": r[2], "actor_type": r[3],
                "actor_id": str(r[4]) if r[4] else None, "resource_type": r[5],
                "target_id": r[6], "request_id": r[7], "payload": r[8],
            }
            for r in rows
        ]
