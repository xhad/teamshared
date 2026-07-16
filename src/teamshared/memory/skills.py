"""Postgres-backed skill memory: atomic agent instruction building blocks.

Skills are smaller and more reusable than playbooks (procedures). A playbook's
``tool_recipe`` may list skill names to compose into a loop; workflows may
reference a skill on a stage. Skills are markdown-first so an agent can read
``body_md`` directly; optional ``tool_hints`` JSON suggests MCP tools to prefer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)


class OrgSkillStore:
    """Org-scoped skill memory over :class:`TenantDb` (RLS-enforced)."""

    _FIELDS = (
        "id", "name", "version", "description", "body_md", "tool_hints", "tags",
        "created_by", "created_at",
    )
    _SELECT = (
        "id, name, version, description, body_md, tool_hints, tags, created_by, created_at"
    )

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def set_skill(
        self,
        org_id: UUID,
        name: str,
        body_md: str,
        *,
        agent: str,
        tool_hints: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        hints_json = json.dumps(tool_hints) if tool_hints is not None else None
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM skills WHERE name = %s",
                (name,),
            )
            row = await cur.fetchone()
            next_version = int(row[0]) if row else 1
            cur = await conn.execute(
                f"INSERT INTO skills "
                f"(org_id, scope, name, version, description, body_md, tool_hints, tags, "
                f" created_by, created_at, status) "
                f"VALUES (%s,'org',%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) RETURNING {self._SELECT}, status",
                (
                    str(org_id), name, next_version, description, body_md, hints_json,
                    tags or [], agent, datetime.now(UTC), status,
                ),
            )
            inserted = await cur.fetchone()
        if inserted is None:
            raise RuntimeError("INSERT did not return a row")
        fields = (*self._FIELDS, "status")
        return dict(zip(fields, inserted, strict=False))

    async def get_skill(
        self, org_id: UUID, name: str, version: int | None = None
    ) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            if version is None:
                cur = await conn.execute(
                    f"SELECT {self._SELECT}, status FROM skills WHERE name = %s "
                    f"AND status = 'active' ORDER BY version DESC LIMIT 1",
                    (name,),
                )
            else:
                cur = await conn.execute(
                    f"SELECT {self._SELECT}, status FROM skills "
                    f"WHERE name = %s AND version = %s AND status = 'active'",
                    (name, version),
                )
            row = await cur.fetchone()
        if row is None:
            return None
        fields = (*self._FIELDS, "status")
        return dict(zip(fields, row, strict=False))

    async def list_skills(
        self,
        org_id: UUID,
        *,
        tag: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, params = self._list_filters(tag=tag, query=query)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT DISTINCT ON (name) {self._SELECT}, status FROM skills "
                f"WHERE {where} "
                f"ORDER BY name, version DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = await cur.fetchall()
        fields = (*self._FIELDS, "status")
        return [dict(zip(fields, r, strict=False)) for r in rows]

    async def count_skills(
        self,
        org_id: UUID,
        *,
        tag: str | None = None,
        query: str | None = None,
    ) -> int:
        where, params = self._list_filters(tag=tag, query=query)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT COUNT(DISTINCT name) FROM skills WHERE {where}",
                params,
            )
            row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    @staticmethod
    def _list_filters(
        *, tag: str | None = None, query: str | None = None
    ) -> tuple[str, tuple[Any, ...]]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        if tag:
            clauses.append("%s = ANY(tags)")
            params.append(tag)
        q = (query or "").strip()
        if q:
            like = f"%{q}%"
            clauses.append(
                "(name ILIKE %s OR coalesce(description, '') ILIKE %s "
                "OR coalesce(body_md, '') ILIKE %s "
                "OR EXISTS (SELECT 1 FROM unnest(coalesce(tags, ARRAY[]::text[])) t "
                "WHERE t ILIKE %s))"
            )
            params.extend([like, like, like, like])
        return " AND ".join(clauses), tuple(params)

    async def forget_by_name(self, org_id: UUID, name: str) -> int:
        """Soft-delete every active version of a skill name. Returns rows updated."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE skills SET status = 'soft_deleted' "
                "WHERE name = %s AND status = 'active'",
                (name,),
            )
            return cur.rowcount or 0

    async def search_skills(self, org_id: UUID, query: str, limit: int = 10) -> list[MemoryRecord]:
        """Lexical search via Postgres full-text on name/description/body_md."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT DISTINCT ON (name)
                    id, name, version, description, body_md, tags, created_by, created_at,
                    ts_rank(
                        to_tsvector('english',
                            coalesce(name,'') || ' ' || coalesce(description,'') || ' ' || coalesce(body_md,'')),
                        plainto_tsquery('english', %s)
                    ) AS rank
                FROM skills
                WHERE status = 'active'
                  AND to_tsvector('english',
                        coalesce(name,'') || ' ' || coalesce(description,'') || ' ' || coalesce(body_md,''))
                      @@ plainto_tsquery('english', %s)
                ORDER BY name, version DESC, rank DESC
                LIMIT %s
                """,
                (query, query, limit),
            )
            rows = await cur.fetchall()
        records: list[MemoryRecord] = []
        for row in rows:
            records.append(
                MemoryRecord(
                    id=str(row[0]),
                    pillar="skill",
                    kind="skill",
                    content=f"{row[1]} (v{row[2]}): {row[3] or (row[4] or '')[:200]}",
                    agent=row[6],
                    tags=list(row[5] or []),
                    score=float(row[8]) if row[8] is not None else None,
                    created_at=row[7],
                    org_id=org_id,
                    metadata={"name": row[1], "version": row[2]},
                )
            )
        return records
