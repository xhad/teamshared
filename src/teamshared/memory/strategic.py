"""Org-scoped strategic memory: vision/mission/purpose and OKR cycles."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord, StrategicEntityType, StrategicStatementKind
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

StrategicRowStatus = Literal[
    "pending_approval", "active", "superseded", "rejected", "closed", "quarantined"
]


class OrgStrategicStore:
    """CRUD over strategic tables under RLS via :class:`TenantDb`."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def set_statement(
        self,
        org_id: UUID,
        kind: StrategicStatementKind,
        content_md: str,
        *,
        agent: str,
        status: str = "pending_approval",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM strategic_statements "
                "WHERE org_id = %s AND kind = %s",
                (str(org_id), kind),
            )
            row = await cur.fetchone()
            next_version = int(row[0]) if row else 1
            cur = await conn.execute(
                """
                INSERT INTO strategic_statements
                    (org_id, kind, content_md, version, status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, kind, content_md, version, status, created_by, created_at
                """,
                (str(org_id), kind, content_md, next_version, status, agent, datetime.now(UTC)),
            )
            inserted = await cur.fetchone()
        if inserted is None:
            raise RuntimeError("INSERT strategic_statements did not return a row")
        return _statement_row(inserted)

    async def get_active_statement(
        self, org_id: UUID, kind: StrategicStatementKind
    ) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, kind, content_md, version, status, created_by, created_at
                FROM strategic_statements
                WHERE kind = %s AND status = 'active'
                ORDER BY version DESC
                LIMIT 1
                """,
                (kind,),
            )
            row = await cur.fetchone()
        return _statement_row(row) if row else None

    async def create_plan(
        self,
        org_id: UUID,
        *,
        name: str,
        period_start: date,
        period_end: date,
        agent: str,
        status: str = "pending_approval",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO strategic_plans
                    (org_id, name, period_start, period_end, status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, name, period_start, period_end, status, created_by, created_at
                """,
                (
                    str(org_id), name, period_start, period_end, status, agent,
                    datetime.now(UTC),
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT strategic_plans did not return a row")
        return _plan_row(row)

    async def list_plans(
        self, org_id: UUID, *, active_only: bool = True, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            if active_only:
                cur = await conn.execute(
                    """
                    SELECT id, org_id, name, period_start, period_end, status, created_by, created_at
                    FROM strategic_plans
                    WHERE status = 'active'
                    ORDER BY period_start DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            else:
                cur = await conn.execute(
                    """
                    SELECT id, org_id, name, period_start, period_end, status, created_by, created_at
                    FROM strategic_plans
                    ORDER BY period_start DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = await cur.fetchall()
        return [_plan_row(r) for r in rows]

    async def get_plan(self, org_id: UUID, plan_id: UUID) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, name, period_start, period_end, status, created_by, created_at
                FROM strategic_plans WHERE id = %s
                """,
                (str(plan_id),),
            )
            row = await cur.fetchone()
        return _plan_row(row) if row else None

    async def get_plan_tree(self, org_id: UUID, plan_id: UUID) -> dict[str, Any] | None:
        plan = await self.get_plan(org_id, plan_id)
        if plan is None:
            return None
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, plan_id, title, description_md, owner_type, owner_id,
                       sort_order, status, created_by, created_at
                FROM strategic_objectives
                WHERE plan_id = %s AND status = 'active'
                ORDER BY sort_order, created_at
                """,
                (str(plan_id),),
            )
            objectives = [_objective_row(r) for r in await cur.fetchall()]
            obj_ids = [str(o["id"]) for o in objectives]
            key_results: dict[str, list[dict[str, Any]]] = {oid: [] for oid in obj_ids}
            if obj_ids:
                cur = await conn.execute(
                    """
                    SELECT id, org_id, objective_id, title, description_md,
                           metric_target, metric_current, metric_unit, track_status,
                           status, created_by, created_at
                    FROM strategic_key_results
                    WHERE objective_id = ANY(%s::uuid[]) AND status = 'active'
                    ORDER BY created_at
                    """,
                    (obj_ids,),
                )
                for r in await cur.fetchall():
                    kr = _key_result_row(r)
                    key_results[str(kr["objective_id"])].append(kr)
            cur = await conn.execute(
                """
                SELECT id, org_id, plan_id, objective_id, key_result_id, title,
                       description_md, status, created_by, created_at
                FROM strategic_initiatives
                WHERE plan_id = %s AND status = 'active'
                ORDER BY created_at
                """,
                (str(plan_id),),
            )
            initiatives = [_initiative_row(r) for r in await cur.fetchall()]
        for obj in objectives:
            obj["key_results"] = key_results.get(str(obj["id"]), [])
            obj["initiatives"] = [i for i in initiatives if str(i.get("objective_id")) == str(obj["id"])]
        unaligned = [i for i in initiatives if i.get("objective_id") is None]
        plan["objectives"] = objectives
        plan["initiatives"] = unaligned
        return plan

    async def create_objective(
        self,
        org_id: UUID,
        *,
        plan_id: UUID,
        title: str,
        description_md: str | None,
        owner_type: str | None,
        owner_id: UUID | None,
        sort_order: int,
        agent: str,
        status: str = "pending_approval",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO strategic_objectives
                    (org_id, plan_id, title, description_md, owner_type, owner_id,
                     sort_order, status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, plan_id, title, description_md, owner_type, owner_id,
                          sort_order, status, created_by, created_at
                """,
                (
                    str(org_id), str(plan_id), title, description_md, owner_type,
                    str(owner_id) if owner_id else None, sort_order, status, agent,
                    datetime.now(UTC),
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT strategic_objectives did not return a row")
        return _objective_row(row)

    async def create_key_result(
        self,
        org_id: UUID,
        *,
        objective_id: UUID,
        title: str,
        description_md: str | None,
        metric_target: float | None,
        metric_current: float | None,
        metric_unit: str | None,
        track_status: str,
        agent: str,
        status: str = "pending_approval",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO strategic_key_results
                    (org_id, objective_id, title, description_md, metric_target, metric_current,
                     metric_unit, track_status, status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, objective_id, title, description_md, metric_target,
                          metric_current, metric_unit, track_status, status, created_by, created_at
                """,
                (
                    str(org_id), str(objective_id), title, description_md, metric_target,
                    metric_current, metric_unit, track_status, status, agent, datetime.now(UTC),
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT strategic_key_results did not return a row")
        return _key_result_row(row)

    async def create_initiative(
        self,
        org_id: UUID,
        *,
        plan_id: UUID,
        title: str,
        description_md: str | None,
        objective_id: UUID | None,
        key_result_id: UUID | None,
        agent: str,
        status: str = "pending_approval",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO strategic_initiatives
                    (org_id, plan_id, objective_id, key_result_id, title, description_md,
                     status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, plan_id, objective_id, key_result_id, title,
                          description_md, status, created_by, created_at
                """,
                (
                    str(org_id), str(plan_id),
                    str(objective_id) if objective_id else None,
                    str(key_result_id) if key_result_id else None,
                    title, description_md, status, agent, datetime.now(UTC),
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT strategic_initiatives did not return a row")
        return _initiative_row(row)

    async def activate(self, org_id: UUID, entity_type: StrategicEntityType, entity_id: UUID) -> None:
        async with self.db.org(org_id) as conn:
            if entity_type == "statement":
                cur = await conn.execute(
                    "SELECT kind FROM strategic_statements WHERE id = %s",
                    (str(entity_id),),
                )
                row = await cur.fetchone()
                if row is None:
                    return
                kind = row[0]
                await conn.execute(
                    "UPDATE strategic_statements SET status = 'superseded' "
                    "WHERE kind = %s AND status = 'active' AND id != %s",
                    (kind, str(entity_id)),
                )
                await conn.execute(
                    "UPDATE strategic_statements SET status = 'active' WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "plan":
                await conn.execute(
                    "UPDATE strategic_plans SET status = 'active' WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "objective":
                await conn.execute(
                    "UPDATE strategic_objectives SET status = 'active' WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "key_result":
                await conn.execute(
                    "UPDATE strategic_key_results SET status = 'active' WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "initiative":
                await conn.execute(
                    "UPDATE strategic_initiatives SET status = 'active' WHERE id = %s",
                    (str(entity_id),),
                )

    async def reject(self, org_id: UUID, entity_type: StrategicEntityType, entity_id: UUID) -> None:
        table = _table_for(entity_type)
        if table is None:
            return
        async with self.db.org(org_id) as conn:
            await conn.execute(
                f"UPDATE {table} SET status = 'rejected' WHERE id = %s",
                (str(entity_id),),
            )

    async def preview_entity(
        self, org_id: UUID, entity_type: StrategicEntityType, entity_id: UUID
    ) -> str | None:
        """Human-readable preview for the approval queue."""
        async with self.db.org(org_id) as conn:
            if entity_type == "statement":
                cur = await conn.execute(
                    "SELECT kind, content_md, version FROM strategic_statements WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "plan":
                cur = await conn.execute(
                    "SELECT name, period_start, period_end FROM strategic_plans WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "objective":
                cur = await conn.execute(
                    "SELECT title, description_md FROM strategic_objectives WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "key_result":
                cur = await conn.execute(
                    "SELECT title, metric_target, metric_current, metric_unit "
                    "FROM strategic_key_results WHERE id = %s",
                    (str(entity_id),),
                )
            elif entity_type == "initiative":
                cur = await conn.execute(
                    "SELECT title, description_md FROM strategic_initiatives WHERE id = %s",
                    (str(entity_id),),
                )
            else:
                return None
            row = await cur.fetchone()
        if row is None:
            return None
        if entity_type == "statement":
            return f"{row[0]} v{row[2]}: {(row[1] or '')[:200]}"
        if entity_type == "plan":
            return f"Plan {row[0]} ({row[1]} – {row[2]})"
        if entity_type == "objective":
            return f"Objective: {row[0]} — {(row[1] or '')[:160]}"
        if entity_type == "key_result":
            unit = row[3] or ""
            return f"Key result: {row[0]} ({row[2] or 0}/{row[1] or '?'}{unit})"
        return f"Initiative: {row[0]} — {(row[1] or '')[:160]}"

    async def search(self, org_id: UUID, query: str, *, limit: int = 8) -> list[MemoryRecord]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT * FROM (
                    SELECT id::text, 'statement' AS etype, kind AS label,
                           content_md AS body, created_at,
                           ts_rank(to_tsvector('english', kind || ' ' || content_md),
                                   plainto_tsquery('english', %s)) AS rank
                    FROM strategic_statements WHERE status = 'active'
                    UNION ALL
                    SELECT id::text, 'plan', name, name, created_at,
                           ts_rank(to_tsvector('english', name), plainto_tsquery('english', %s))
                    FROM strategic_plans WHERE status = 'active'
                    UNION ALL
                    SELECT id::text, 'objective', title,
                           coalesce(title,'') || ' ' || coalesce(description_md,''),
                           created_at,
                           ts_rank(to_tsvector('english', title || ' ' || coalesce(description_md,'')),
                                   plainto_tsquery('english', %s))
                    FROM strategic_objectives WHERE status = 'active'
                    UNION ALL
                    SELECT id::text, 'key_result', title,
                           coalesce(title,'') || ' ' || coalesce(description_md,''),
                           created_at,
                           ts_rank(to_tsvector('english', title || ' ' || coalesce(description_md,'')),
                                   plainto_tsquery('english', %s))
                    FROM strategic_key_results WHERE status = 'active'
                    UNION ALL
                    SELECT id::text, 'initiative', title,
                           coalesce(title,'') || ' ' || coalesce(description_md,''),
                           created_at,
                           ts_rank(to_tsvector('english', title || ' ' || coalesce(description_md,'')),
                                   plainto_tsquery('english', %s))
                    FROM strategic_initiatives WHERE status = 'active'
                ) hits
                WHERE rank > 0
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, query, query, query, query, limit),
            )
            rows = await cur.fetchall()
        out: list[MemoryRecord] = []
        for r in rows:
            etype, label, body = r[1], r[2], r[3]
            prefix = etype.replace("_", " ").title()
            out.append(
                MemoryRecord(
                    id=r[0],
                    pillar="strategic",
                    kind="note",
                    content=f"{prefix}: {label} — {(body or '')[:300]}",
                    score=float(r[5]) if r[5] is not None else None,
                    created_at=r[4],
                    org_id=org_id,
                )
            )
        return out

    async def stats(self, org_id: UUID) -> dict[str, int]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM strategic_plans WHERE status = 'active'),
                    (SELECT count(*) FROM strategic_objectives WHERE status = 'active'),
                    (SELECT count(*) FROM strategic_statements WHERE status = 'active')
                """,
            )
            row = await cur.fetchone()
        if row is None:
            return {"plans": 0, "objectives": 0, "statements": 0}
        return {"plans": int(row[0]), "objectives": int(row[1]), "statements": int(row[2])}


def _table_for(entity_type: StrategicEntityType) -> str | None:
    return {
        "statement": "strategic_statements",
        "plan": "strategic_plans",
        "objective": "strategic_objectives",
        "key_result": "strategic_key_results",
        "initiative": "strategic_initiatives",
    }.get(entity_type)


def _statement_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "kind": row[2],
        "content_md": row[3],
        "version": row[4],
        "status": row[5],
        "created_by": row[6],
        "created_at": row[7],
    }


def _plan_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "name": row[2],
        "period_start": row[3],
        "period_end": row[4],
        "status": row[5],
        "created_by": row[6],
        "created_at": row[7],
    }


def _objective_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "plan_id": row[2],
        "title": row[3],
        "description_md": row[4],
        "owner_type": row[5],
        "owner_id": row[6],
        "sort_order": row[7],
        "status": row[8],
        "created_by": row[9],
        "created_at": row[10],
    }


def _key_result_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "objective_id": row[2],
        "title": row[3],
        "description_md": row[4],
        "metric_target": row[5],
        "metric_current": row[6],
        "metric_unit": row[7],
        "track_status": row[8],
        "status": row[9],
        "created_by": row[10],
        "created_at": row[11],
    }


def _initiative_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "plan_id": row[2],
        "objective_id": row[3],
        "key_result_id": row[4],
        "title": row[5],
        "description_md": row[6],
        "status": row[7],
        "created_by": row[8],
        "created_at": row[9],
    }
