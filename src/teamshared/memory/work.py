"""Org-scoped work items — shared task queue for humans and agents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

WorkStatus = Literal["backlog", "todo", "in_progress", "blocked", "done", "cancelled"]
WorkPriority = Literal["urgent", "high", "normal", "low"]
WorkApprovalStatus = Literal["active", "pending_approval", "rejected", "closed"]
WorkSort = Literal["updated_at", "priority", "work_status", "created_at"]
WorkSortDir = Literal["asc", "desc"]
PartyType = Literal["user", "agent"]

_WORK_STATUSES: frozenset[str] = frozenset(
    {"backlog", "todo", "in_progress", "blocked", "done", "cancelled"}
)
_PRIORITIES: frozenset[str] = frozenset({"urgent", "high", "normal", "low"})


class WorkStore:
    """CRUD over ``work_items`` under RLS via :class:`TenantDb`."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def create(
        self,
        org_id: UUID,
        *,
        title: str,
        description_md: str | None,
        tags: list[str] | None,
        work_status: WorkStatus,
        priority: WorkPriority,
        requester_type: PartyType | None,
        requester_id: UUID | None,
        assignee_type: PartyType | None,
        assignee_id: UUID | None,
        initiative_id: UUID | None,
        due_at: datetime | None,
        repo: str | None,
        github: str | None,
        source: str,
        agent: str,
        status: WorkApprovalStatus = "active",
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO work_items (
                    org_id, initiative_id, title, description_md, tags,
                    work_status, priority, blocked_reason,
                    requester_type, requester_id, assignee_type, assignee_id,
                    due_at, repo, github, source, status, created_by,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                RETURNING
                    id, org_id, initiative_id, title, description_md, tags,
                    work_status, priority, blocked_reason,
                    requester_type, requester_id, assignee_type, assignee_id,
                    due_at, repo, github, source, status, created_by,
                    created_at, updated_at, closed_at
                """,
                (
                    str(org_id),
                    str(initiative_id) if initiative_id else None,
                    title,
                    description_md,
                    tags or [],
                    work_status,
                    priority,
                    blocked_reason,
                    requester_type,
                    str(requester_id) if requester_id else None,
                    assignee_type,
                    str(assignee_id) if assignee_id else None,
                    due_at,
                    repo,
                    github,
                    source,
                    status,
                    agent,
                    now,
                    now,
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT work_items did not return a row")
        return _row(row)

    async def get(self, org_id: UUID, work_id: UUID) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT
                    id, org_id, initiative_id, title, description_md, tags,
                    work_status, priority, blocked_reason,
                    requester_type, requester_id, assignee_type, assignee_id,
                    due_at, repo, github, source, status, created_by,
                    created_at, updated_at, closed_at
                FROM work_items WHERE id = %s
                """,
                (str(work_id),),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        item = _row(row)
        await self.enrich_labels(org_id, [item])
        return item

    async def list_items(
        self,
        org_id: UUID,
        *,
        work_status: WorkStatus | None = None,
        assignee_type: PartyType | None = None,
        assignee_id: UUID | None = None,
        initiative_id: UUID | None = None,
        approval_status: WorkApprovalStatus = "active",
        exclude_closed: bool = True,
        sort: WorkSort = "updated_at",
        sort_dir: WorkSortDir = "desc",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = ["status = %s"]
        params: list[Any] = [approval_status]
        if work_status is not None:
            clauses.append("work_status = %s")
            params.append(work_status)
        elif exclude_closed:
            clauses.append("work_status NOT IN ('done', 'cancelled')")
        if assignee_type is not None:
            clauses.append("assignee_type = %s")
            params.append(assignee_type)
            if assignee_id is not None:
                clauses.append("assignee_id = %s")
                params.append(str(assignee_id))
            else:
                clauses.append("assignee_id IS NULL")
        if initiative_id is not None:
            clauses.append("initiative_id = %s")
            params.append(str(initiative_id))
        order = _order_clause(sort, sort_dir)
        params.append(limit)
        where = " AND ".join(clauses)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                SELECT
                    id, org_id, initiative_id, title, description_md, tags,
                    work_status, priority, blocked_reason,
                    requester_type, requester_id, assignee_type, assignee_id,
                    due_at, repo, github, source, status, created_by,
                    created_at, updated_at, closed_at
                FROM work_items
                WHERE {where}
                ORDER BY {order}
                LIMIT %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()
        items = [_row(r) for r in rows]
        await self.enrich_labels(org_id, items)
        return items

    async def update(
        self,
        org_id: UUID,
        work_id: UUID,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        allowed = {
            "title", "description_md", "tags", "work_status", "priority",
            "blocked_reason", "assignee_type", "assignee_id",
            "requester_type", "requester_id", "initiative_id",
            "due_at", "repo", "github",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, val in fields.items():
            if key not in allowed:
                continue
            if key == "work_status" and val not in _WORK_STATUSES:
                continue
            if key == "priority" and val not in _PRIORITIES:
                continue
            if key in {"assignee_id", "requester_id", "initiative_id"} and val is not None:
                val = str(val)
            updates.append(f"{key} = %s")
            params.append(val)
        if not updates:
            return await self.get(org_id, work_id)
        updates.append("updated_at = %s")
        params.append(datetime.now(UTC))
        params.extend([str(work_id)])
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                UPDATE work_items SET {", ".join(updates)}
                WHERE id = %s AND status = 'active'
                RETURNING
                    id, org_id, initiative_id, title, description_md, tags,
                    work_status, priority, blocked_reason,
                    requester_type, requester_id, assignee_type, assignee_id,
                    due_at, repo, github, source, status, created_by,
                    created_at, updated_at, closed_at
                """,
                tuple(params),
            )
            row = await cur.fetchone()
        return _row(row) if row else None

    async def close(
        self,
        org_id: UUID,
        work_id: UUID,
        *,
        work_status: WorkStatus = "done",
    ) -> dict[str, Any] | None:
        if work_status not in {"done", "cancelled"}:
            work_status = "done"
        now = datetime.now(UTC)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                UPDATE work_items
                SET work_status = %s, closed_at = %s, updated_at = %s
                WHERE id = %s AND status = 'active'
                RETURNING
                    id, org_id, initiative_id, title, description_md, tags,
                    work_status, priority, blocked_reason,
                    requester_type, requester_id, assignee_type, assignee_id,
                    due_at, repo, github, source, status, created_by,
                    created_at, updated_at, closed_at
                """,
                (work_status, now, now, str(work_id)),
            )
            row = await cur.fetchone()
        return _row(row) if row else None

    async def activate(self, org_id: UUID, work_id: UUID) -> None:
        async with self.db.org(org_id) as conn:
            await conn.execute(
                "UPDATE work_items SET status = 'active', updated_at = now() WHERE id = %s",
                (str(work_id),),
            )

    async def reject(self, org_id: UUID, work_id: UUID) -> None:
        async with self.db.org(org_id) as conn:
            await conn.execute(
                "UPDATE work_items SET status = 'rejected', updated_at = now() WHERE id = %s",
                (str(work_id),),
            )

    async def preview(self, org_id: UUID, work_id: UUID) -> str | None:
        row = await self.get(org_id, work_id)
        if row is None:
            return None
        assignee = _party_label(row.get("assignee_type"), row.get("assignee_id"))
        return (
            f"Work: {row.get('title')} [{row.get('work_status')}/{row.get('priority')}]"
            f"{f' → {assignee}' if assignee else ''}"
        )

    async def resolve_agent_id(self, org_id: UUID, name: str) -> UUID | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id FROM agents WHERE name = %s AND status = 'active'",
                (name,),
            )
            row = await cur.fetchone()
        return row[0] if row else None

    async def resolve_user_id_by_email(self, org_id: UUID, email: str) -> UUID | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT u.id FROM users u
                JOIN memberships m ON m.user_id = u.id
                WHERE lower(u.email) = lower(%s)
                LIMIT 1
                """,
                (email.strip(),),
            )
            row = await cur.fetchone()
        return row[0] if row else None

    async def search(self, org_id: UUID, query: str, *, limit: int = 8) -> list[MemoryRecord]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT
                    id::text, title, description_md, work_status, priority,
                    assignee_type, assignee_id, created_at,
                    ts_rank(
                        to_tsvector(
                            'english',
                            coalesce(title, '') || ' ' || coalesce(description_md, '')
                            || ' ' || coalesce(blocked_reason, '')
                        ),
                        plainto_tsquery('english', %s)
                    ) AS rank
                FROM work_items
                WHERE status = 'active'
                  AND to_tsvector(
                        'english',
                        coalesce(title, '') || ' ' || coalesce(description_md, '')
                        || ' ' || coalesce(blocked_reason, '')
                    ) @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, query, limit),
            )
            rows = await cur.fetchall()
        out: list[MemoryRecord] = []
        for r in rows:
            assignee = _party_label(r[5], r[6])
            body = f"{r[1]} — status={r[3]}, priority={r[4]}"
            if assignee:
                body += f", assignee={assignee}"
            if r[2]:
                body += f". {(r[2] or '')[:200]}"
            out.append(
                MemoryRecord(
                    id=r[0],
                    pillar="work",
                    kind="note",
                    content=f"Work: {body}",
                    score=float(r[8]) if r[8] is not None else None,
                    created_at=r[7],
                    org_id=org_id,
                )
            )
        return out

    async def enrich_labels(self, org_id: UUID, items: list[dict[str, Any]]) -> None:
        """Attach human-readable assignee/requester/initiative labels in-place."""
        if not items:
            return
        agent_ids: set[str] = set()
        user_ids: set[str] = set()
        initiative_ids: set[str] = set()
        for item in items:
            for party_key in ("assignee", "requester"):
                ptype = item.get(f"{party_key}_type")
                pid = item.get(f"{party_key}_id")
                if ptype == "agent" and pid:
                    agent_ids.add(str(pid))
                elif ptype == "user" and pid:
                    user_ids.add(str(pid))
            if item.get("initiative_id"):
                initiative_ids.add(str(item["initiative_id"]))
        agent_names: dict[str, str] = {}
        user_labels: dict[str, str] = {}
        initiative_titles: dict[str, str] = {}
        async with self.db.org(org_id) as conn:
            if agent_ids:
                cur = await conn.execute(
                    "SELECT id::text, name FROM agents WHERE id = ANY(%s::uuid[])",
                    (list(agent_ids),),
                )
                for r in await cur.fetchall():
                    agent_names[r[0]] = r[1]
            if user_ids:
                cur = await conn.execute(
                    "SELECT id::text, coalesce(name, email) FROM users WHERE id = ANY(%s::uuid[])",
                    (list(user_ids),),
                )
                for r in await cur.fetchall():
                    user_labels[r[0]] = r[1]
            if initiative_ids:
                cur = await conn.execute(
                    "SELECT id::text, title FROM strategic_initiatives WHERE id = ANY(%s::uuid[])",
                    (list(initiative_ids),),
                )
                for r in await cur.fetchall():
                    initiative_titles[r[0]] = r[1]
        for item in items:
            item["assignee_label"] = _resolve_label(
                item.get("assignee_type"), item.get("assignee_id"), agent_names, user_labels,
            )
            item["requester_label"] = _resolve_label(
                item.get("requester_type"), item.get("requester_id"), agent_names, user_labels,
            )
            init_id = item.get("initiative_id")
            item["initiative_title"] = (
                initiative_titles.get(str(init_id)) if init_id else None
            )

    async def add_comment(
        self,
        org_id: UUID,
        work_id: UUID,
        *,
        author_type: PartyType,
        author_id: UUID,
        body_md: str,
    ) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO work_comments (org_id, work_item_id, author_type, author_id, body_md)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, org_id, work_item_id, author_type, author_id, body_md, created_at
                """,
                (str(org_id), str(work_id), author_type, str(author_id), body_md),
            )
            row = await cur.fetchone()
        assert row is not None
        return _comment_row(row)

    async def list_comments(
        self,
        org_id: UUID,
        work_id: UUID,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, org_id, work_item_id, author_type, author_id, body_md, created_at
                FROM work_comments
                WHERE work_item_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (str(work_id), limit),
            )
            rows = await cur.fetchall()
        comments = [_comment_row(r) for r in rows]
        await self._enrich_comment_authors(org_id, comments)
        return comments

    async def _enrich_comment_authors(
        self, org_id: UUID, comments: list[dict[str, Any]],
    ) -> None:
        if not comments:
            return
        agent_ids: set[str] = set()
        user_ids: set[str] = set()
        for c in comments:
            if c["author_type"] == "agent":
                agent_ids.add(str(c["author_id"]))
            elif c["author_type"] == "user":
                user_ids.add(str(c["author_id"]))
        agent_names: dict[str, str] = {}
        user_labels: dict[str, str] = {}
        async with self.db.org(org_id) as conn:
            if agent_ids:
                cur = await conn.execute(
                    "SELECT id::text, name FROM agents WHERE id = ANY(%s::uuid[])",
                    (list(agent_ids),),
                )
                for r in await cur.fetchall():
                    agent_names[r[0]] = r[1]
            if user_ids:
                cur = await conn.execute(
                    "SELECT id::text, coalesce(name, email) FROM users WHERE id = ANY(%s::uuid[])",
                    (list(user_ids),),
                )
                for r in await cur.fetchall():
                    user_labels[r[0]] = r[1]
        for c in comments:
            c["author_label"] = _resolve_label(
                c.get("author_type"), c.get("author_id"), agent_names, user_labels,
            )

    async def stats(self, org_id: UUID) -> dict[str, int]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'active'),
                    count(*) FILTER (
                        WHERE status = 'active' AND work_status NOT IN ('done', 'cancelled')
                    ),
                    count(*) FILTER (WHERE status = 'active' AND work_status = 'blocked'),
                    count(*) FILTER (WHERE status = 'pending_approval')
                FROM work_items
                """,
            )
            row = await cur.fetchone()
        if row is None:
            return {"total": 0, "open": 0, "blocked": 0, "pending_approval": 0}
        return {
            "total": int(row[0]),
            "open": int(row[1]),
            "blocked": int(row[2]),
            "pending_approval": int(row[3]),
        }


def _party_label(party_type: Any, party_id: Any) -> str | None:
    if party_type and party_id:
        return f"{party_type}:{party_id}"
    return None


def _resolve_label(
    party_type: Any,
    party_id: Any,
    agent_names: dict[str, str],
    user_labels: dict[str, str],
) -> str | None:
    if not party_type or not party_id:
        return None
    pid = str(party_id)
    if party_type == "agent":
        return agent_names.get(pid) or f"agent:{pid[:8]}"
    if party_type == "user":
        return user_labels.get(pid) or f"user:{pid[:8]}"
    return None


def _order_clause(sort: WorkSort, sort_dir: WorkSortDir) -> str:
    direction = "ASC" if sort_dir == "asc" else "DESC"
    if sort == "priority":
        expr = (
            "CASE priority "
            "WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'normal' THEN 2 ELSE 3 END"
        )
    elif sort == "work_status":
        expr = (
            "CASE work_status "
            "WHEN 'blocked' THEN 0 WHEN 'in_progress' THEN 1 "
            "WHEN 'todo' THEN 2 WHEN 'backlog' THEN 3 "
            "WHEN 'done' THEN 4 ELSE 5 END"
        )
    else:
        expr = sort
    return f"{expr} {direction}, updated_at DESC"


def _comment_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "work_item_id": row[2],
        "author_type": row[3],
        "author_id": row[4],
        "body_md": row[5],
        "created_at": row[6],
        "author_label": None,
    }


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "org_id": row[1],
        "initiative_id": row[2],
        "title": row[3],
        "description_md": row[4],
        "tags": list(row[5] or []),
        "work_status": row[6],
        "priority": row[7],
        "blocked_reason": row[8],
        "requester_type": row[9],
        "requester_id": row[10],
        "assignee_type": row[11],
        "assignee_id": row[12],
        "due_at": row[13],
        "repo": row[14],
        "github": row[15],
        "source": row[16],
        "status": row[17],
        "created_by": row[18],
        "created_at": row[19],
        "updated_at": row[20],
        "closed_at": row[21],
    }
