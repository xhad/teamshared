"""Approval queue: human-in-the-loop gate for memories and procedures that need review."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.memory.strategic import OrgStrategicStore
from teamshared.memory.types import StrategicEntityType
from teamshared.memory.work import WorkStore
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

    async def enqueue_work(
        self,
        org_id: UUID,
        work_item_id: UUID,
        *,
        reason: str,
        requested_by: UUID | None = None,
    ) -> UUID:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO approval_queue (org_id, work_item_id, reason, requested_by) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (
                    str(org_id), str(work_item_id), reason,
                    str(requested_by) if requested_by else None,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        approval_id: UUID = row[0]
        return approval_id

    async def enqueue_strategic(
        self,
        org_id: UUID,
        entity_type: str,
        entity_id: UUID,
        *,
        reason: str,
        requested_by: UUID | None = None,
    ) -> UUID:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO approval_queue "
                "(org_id, strategic_entity_type, strategic_entity_id, reason, requested_by) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (
                    str(org_id), entity_type, str(entity_id), reason,
                    str(requested_by) if requested_by else None,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        approval_id: UUID = row[0]
        return approval_id

    async def list_pending(self, org_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        strategic = OrgStrategicStore(self.db)
        work = WorkStore(self.db)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT aq.id, aq.memory_id, aq.procedure_id, aq.strategic_entity_type,
                       aq.strategic_entity_id, aq.work_item_id, aq.reason, aq.created_at,
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
        out: list[dict[str, Any]] = []
        for r in rows:
            content = r[8]
            entity_type = r[3]
            entity_id = r[4]
            work_item_id = r[5]
            if work_item_id and not content:
                preview = await work.preview(org_id, UUID(str(work_item_id)))
                content = preview or f"work item {work_item_id}"
            elif entity_type and entity_id and not content:
                preview = await strategic.preview_entity(
                    org_id, entity_type, UUID(str(entity_id))
                )
                content = preview or f"strategic {entity_type} {entity_id}"
            out.append(
                {
                    "id": str(r[0]),
                    "memory_id": str(r[1]) if r[1] else None,
                    "procedure_id": str(r[2]) if r[2] else None,
                    "strategic_entity_type": entity_type,
                    "strategic_entity_id": str(entity_id) if entity_id else None,
                    "work_item_id": str(work_item_id) if work_item_id else None,
                    "reason": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                    "content": content,
                }
            )
        return out

    async def decide(
        self, org_id: UUID, approval_id: UUID, *, approved: bool, decided_by: UUID | None = None
    ) -> UUID | None:
        """Approve/reject. Returns the affected ``memory_id`` when applicable."""
        status = "approved" if approved else "rejected"
        strategic = OrgStrategicStore(self.db)
        work = WorkStore(self.db)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE approval_queue SET status = %s, decided_by = %s, decided_at = now() "
                "WHERE id = %s AND status = 'pending' "
                "RETURNING memory_id, procedure_id, strategic_entity_type, strategic_entity_id, "
                "work_item_id",
                (status, str(decided_by) if decided_by else None, str(approval_id)),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            memory_id, procedure_id, entity_type, entity_id, work_item_id = (
                row[0], row[1], row[2], row[3], row[4],
            )
            if work_item_id:
                wid = UUID(str(work_item_id))
                if approved:
                    await work.activate(org_id, wid)
                else:
                    await work.reject(org_id, wid)
                return None
            if entity_type and entity_id:
                etype: StrategicEntityType = entity_type
                eid = UUID(str(entity_id))
                if approved:
                    await strategic.activate(org_id, etype, eid)
                else:
                    await strategic.reject(org_id, etype, eid)
                return None
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
        return UUID(str(memory_id)) if memory_id is not None else None
