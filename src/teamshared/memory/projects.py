"""Org-scoped projects — Asana-style containers for work items.

A project groups tasks, belongs to an optional team, and may roll up to a
strategic initiative (portfolio analogue). Sections are ordered buckets within a
project (list groups / board columns); members are humans and agents with
access; status updates are the periodic on-track / at-risk / off-track banner.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.wiki import slugify
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

ProjectStatus = Literal["active", "archived"]
ProjectView = Literal["list", "board", "timeline", "calendar"]
ProjectUpdateState = Literal["on_track", "at_risk", "off_track"]
PartyType = Literal["user", "agent"]

_VIEWS: frozenset[str] = frozenset({"list", "board", "timeline", "calendar"})
_UPDATE_STATES: frozenset[str] = frozenset({"on_track", "at_risk", "off_track"})

_PROJECT_COLS = (
    "id, org_id, team_id, slug, name, description_md, project_status, "
    "default_view, color, owner_id, initiative_id, created_by, "
    "created_at, updated_at, archived_at"
)


class ProjectStore:
    """CRUD over ``projects`` and its child tables under RLS via :class:`TenantDb`."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def create(
        self,
        org_id: UUID,
        *,
        name: str,
        description_md: str | None = None,
        team_id: UUID | None = None,
        default_view: ProjectView = "list",
        color: str | None = None,
        owner_id: UUID | None = None,
        initiative_id: UUID | None = None,
        created_by: str,
        slug: str | None = None,
    ) -> dict[str, Any]:
        if default_view not in _VIEWS:
            default_view = "list"
        now = datetime.now(UTC)
        async with self.db.org(org_id) as conn:
            resolved_slug = await self._unique_slug(conn, org_id, slug or slugify(name))
            cur = await conn.execute(
                f"""
                INSERT INTO projects (
                    org_id, team_id, slug, name, description_md, project_status,
                    default_view, color, owner_id, initiative_id, created_by,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_PROJECT_COLS}
                """,
                (
                    str(org_id),
                    str(team_id) if team_id else None,
                    resolved_slug,
                    name,
                    description_md,
                    default_view,
                    color,
                    str(owner_id) if owner_id else None,
                    str(initiative_id) if initiative_id else None,
                    created_by,
                    now,
                    now,
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT projects did not return a row")
        return _project_row(row)

    async def _unique_slug(self, conn: Any, org_id: UUID, base: str) -> str:
        candidate = base
        suffix = 2
        while True:
            cur = await conn.execute(
                "SELECT 1 FROM projects WHERE org_id = %s AND slug = %s",
                (str(org_id), candidate),
            )
            if await cur.fetchone() is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1

    async def get(self, org_id: UUID, project_id: UUID) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_PROJECT_COLS} FROM projects WHERE id = %s",
                (str(project_id),),
            )
            row = await cur.fetchone()
        return _project_row(row) if row else None

    async def list_projects(
        self,
        org_id: UUID,
        *,
        team_id: UUID | None = None,
        initiative_id: UUID | None = None,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_archived:
            clauses.append("project_status = 'active'")
        if team_id is not None:
            clauses.append("team_id = %s")
            params.append(str(team_id))
        if initiative_id is not None:
            clauses.append("initiative_id = %s")
            params.append(str(initiative_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT {_PROJECT_COLS} FROM projects
                {where}
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()
        return [_project_row(r) for r in rows]

    async def update(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        allowed = {
            "name", "description_md", "team_id", "default_view",
            "color", "owner_id", "initiative_id", "project_status",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, val in fields.items():
            if key not in allowed:
                continue
            if key == "default_view" and val not in _VIEWS:
                continue
            if key in {"team_id", "owner_id", "initiative_id"} and val is not None:
                val = str(val)
            updates.append(f"{key} = %s")
            params.append(val)
        if not updates:
            return await self.get(org_id, project_id)
        updates.append("updated_at = %s")
        params.append(datetime.now(UTC))
        params.append(str(project_id))
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE projects SET {", ".join(updates)}
                WHERE id = %s
                RETURNING {_PROJECT_COLS}
                """,
                tuple(params),
            )
            row = await cur.fetchone()
        return _project_row(row) if row else None

    async def archive(
        self, org_id: UUID, project_id: UUID, *, archived: bool = True
    ) -> dict[str, Any] | None:
        status = "archived" if archived else "active"
        archived_at = datetime.now(UTC) if archived else None
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE projects
                SET project_status = %s, archived_at = %s, updated_at = now()
                WHERE id = %s
                RETURNING {_PROJECT_COLS}
                """,
                (status, archived_at, str(project_id)),
            )
            row = await cur.fetchone()
        return _project_row(row) if row else None

    # -- sections ---------------------------------------------------------

    async def add_section(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        name: str,
        sort_order: float | None = None,
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            if sort_order is None:
                cur = await conn.execute(
                    "SELECT coalesce(max(sort_order), 0) + 1 FROM project_sections "
                    "WHERE project_id = %s",
                    (str(project_id),),
                )
                row = await cur.fetchone()
                sort_order = float(row[0]) if row else 0.0
            cur = await conn.execute(
                """
                INSERT INTO project_sections (org_id, project_id, name, sort_order)
                VALUES (%s, %s, %s, %s)
                RETURNING id, org_id, project_id, name, sort_order, created_at
                """,
                (str(org_id), str(project_id), name, sort_order),
            )
            row = await cur.fetchone()
        assert row is not None
        return _section_row(row)

    async def list_sections(self, org_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, project_id, name, sort_order, created_at
                FROM project_sections
                WHERE project_id = %s
                ORDER BY sort_order ASC, created_at ASC
                """,
                (str(project_id),),
            )
            rows = await cur.fetchall()
        return [_section_row(r) for r in rows]

    # -- members ----------------------------------------------------------

    async def add_member(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        member_type: PartyType,
        member_id: UUID,
        role: str = "member",
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO project_members (org_id, project_id, member_type, member_id, role)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (org_id, project_id, member_type, member_id)
                DO UPDATE SET role = EXCLUDED.role
                RETURNING id, org_id, project_id, member_type, member_id, role, created_at
                """,
                (str(org_id), str(project_id), member_type, str(member_id), role),
            )
            row = await cur.fetchone()
        assert row is not None
        return _member_row(row)

    async def list_members(self, org_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, project_id, member_type, member_id, role, created_at
                FROM project_members
                WHERE project_id = %s
                ORDER BY created_at ASC
                """,
                (str(project_id),),
            )
            rows = await cur.fetchall()
        return [_member_row(r) for r in rows]

    # -- status updates ---------------------------------------------------

    async def post_status(
        self,
        org_id: UUID,
        project_id: UUID,
        *,
        state: ProjectUpdateState,
        body_md: str | None,
        author_type: PartyType,
        author_id: UUID,
    ) -> dict[str, Any]:
        if state not in _UPDATE_STATES:
            state = "on_track"
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO project_status_updates
                    (org_id, project_id, state, body_md, author_type, author_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, project_id, state, body_md,
                          author_type, author_id, created_at
                """,
                (str(org_id), str(project_id), state, body_md, author_type, str(author_id)),
            )
            row = await cur.fetchone()
        assert row is not None
        return _status_row(row)

    async def latest_status(
        self, org_id: UUID, project_id: UUID
    ) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, project_id, state, body_md,
                       author_type, author_id, created_at
                FROM project_status_updates
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (str(project_id),),
            )
            row = await cur.fetchone()
        return _status_row(row) if row else None


def _project_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "team_id": row[2],
        "slug": row[3],
        "name": row[4],
        "description_md": row[5],
        "project_status": row[6],
        "default_view": row[7],
        "color": row[8],
        "owner_id": row[9],
        "initiative_id": row[10],
        "created_by": row[11],
        "created_at": row[12],
        "updated_at": row[13],
        "archived_at": row[14],
    }


def _section_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "project_id": row[2],
        "name": row[3],
        "sort_order": row[4],
        "created_at": row[5],
    }


def _member_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "project_id": row[2],
        "member_type": row[3],
        "member_id": row[4],
        "role": row[5],
        "created_at": row[6],
    }


def _status_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "project_id": row[2],
        "state": row[3],
        "body_md": row[4],
        "author_type": row[5],
        "author_id": row[6],
        "created_at": row[7],
    }
