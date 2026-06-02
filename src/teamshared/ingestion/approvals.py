"""Approval queue: human-in-the-loop gate for memories and procedures that need review."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb


class ApprovalQueue:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def enqueue(
        self, org_id: UUID, memory_id: UUID, *, reason: str, requested_by: UUID | None = None
    ) -> UUID:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO approval_queue (org_id, memory_id, reason, requested_by) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (str(org_id), str(memory_id), reason, str(requested_by) if requested_by else None),
            )
            row = await cur.fetchone()
        assert row is not None
        approval_id: UUID = row[0]
        return approval_id

    async def enqueue_procedure(
        self,
        org_id: UUID,
        procedure_id: int,
        *,
        reason: str,
        requested_by: UUID | None = None,
    ) -> UUID:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO approval_queue (org_id, procedure_id, reason, requested_by) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (str(org_id), procedure_id, reason, str(requested_by) if requested_by else None),
            )
            row = await cur.fetchone()
        assert row is not None
        approval_id: UUID = row[0]
        return approval_id

    async def list_pending(self, org_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT aq.id, aq.memory_id, aq.procedure_id, aq.reason, aq.created_at,
                       COALESCE(mi.content, pr.name || ' v' || pr.version::text || ': ' || pr.steps_md)
                FROM approval_queue aq
                LEFT JOIN memory_items mi ON mi.id = aq.memory_id
                LEFT JOIN procedures pr ON pr.id = aq.procedure_id
                WHERE aq.status = 'pending'
                ORDER BY aq.created_at
                LIMIT %s
                """,
                (limit,),
            )
            rows = await cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "memory_id": str(r[1]) if r[1] else None,
                "procedure_id": str(r[2]) if r[2] else None,
                "reason": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "content": r[5],
            }
            for r in rows
        ]

    async def decide(
        self, org_id: UUID, approval_id: UUID, *, approved: bool, decided_by: UUID | None = None
    ) -> UUID | None:
        """Approve/reject. Returns the affected ``memory_id`` when applicable."""
        status = "approved" if approved else "rejected"
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE approval_queue SET status = %s, decided_by = %s, decided_at = now() "
                "WHERE id = %s AND status = 'pending' "
                "RETURNING memory_id, procedure_id",
                (status, str(decided_by) if decided_by else None, str(approval_id)),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            memory_id, procedure_id = row[0], row[1]
            if procedure_id is not None:
                proc_status = "active" if approved else "soft_deleted"
                await conn.execute(
                    "UPDATE procedures SET status = %s WHERE id = %s",
                    (proc_status, procedure_id),
                )
                return None
            new_item_status = "active" if approved else "soft_deleted"
            await conn.execute(
                "UPDATE memory_items SET status = %s, updated_at = now() WHERE id = %s",
                (new_item_status, str(memory_id)),
            )
        return memory_id
