"""CRUD for orgs/users/teams/projects/memberships over RLS-scoped connections.

Org creation goes through the ``provision_organization`` SECURITY DEFINER
function (the only write that predates a tenant context). Every other method
runs inside :meth:`TenantDb.org`, so the database itself rejects any attempt
to touch another tenant's rows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.models import Membership, Organization, Project, Team, User


class TenancyRepository:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def create_organization(self, slug: str, name: str) -> Organization:
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT id, slug, name, status, settings, created_at, updated_at "
                "FROM provision_organization(%s, %s)",
                (slug, name),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("provision_organization returned no row")
        return _org(row)

    async def get_organization(self, org_id: UUID) -> Organization | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, slug, name, status, settings, created_at, updated_at "
                "FROM organizations WHERE id = %s",
                (str(org_id),),
            )
            row = await cur.fetchone()
        return _org(row) if row else None

    async def create_user(
        self,
        org_id: UUID,
        email: str,
        display_name: str | None = None,
        account_id: UUID | None = None,
    ) -> User:
        """Create (or re-activate) the per-org user row, linked to a global account.

        Idempotent on ``(org_id, email)`` so adding the same email twice just
        re-activates and (re)links it rather than failing.
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO users (org_id, email, display_name, account_id) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (org_id, email) DO UPDATE SET "
                "  display_name = COALESCE(EXCLUDED.display_name, users.display_name), "
                "  status = 'active', "
                "  account_id = COALESCE(EXCLUDED.account_id, users.account_id), "
                "  updated_at = now() "
                "RETURNING id, org_id, email, display_name, status, created_at",
                (str(org_id), email, display_name, str(account_id) if account_id else None),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("user insert returned no row")
        return _user(row)

    async def add_membership(self, org_id: UUID, user_id: UUID, role: str = "member") -> Membership:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, %s) "
                "ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role "
                "RETURNING id, org_id, user_id, role, created_at",
                (str(org_id), str(user_id), role),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("membership insert returned no row")
        return _membership(row)

    async def create_team(self, org_id: UUID, slug: str, name: str) -> Team:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO teams (org_id, slug, name) VALUES (%s, %s, %s) "
                "RETURNING id, org_id, slug, name, created_at",
                (str(org_id), slug, name),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("team insert returned no row")
        return _team(row)

    async def create_project(
        self, org_id: UUID, slug: str, name: str, team_id: UUID | None = None
    ) -> Project:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO projects (org_id, team_id, slug, name) VALUES (%s, %s, %s, %s) "
                "RETURNING id, org_id, team_id, slug, name, created_at",
                (str(org_id), str(team_id) if team_id else None, slug, name),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("project insert returned no row")
        return _project(row)

    async def list_teams(self, org_id: UUID) -> list[Team]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, org_id, slug, name, created_at FROM teams ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [_team(r) for r in rows]

    async def list_projects(self, org_id: UUID) -> list[Project]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, org_id, team_id, slug, name, created_at FROM projects ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [_project(r) for r in rows]


def _org(row: tuple[Any, ...]) -> Organization:
    return Organization(
        id=row[0], slug=row[1], name=row[2], status=row[3],
        settings=row[4] or {}, created_at=row[5], updated_at=row[6],
    )


def _user(row: tuple[Any, ...]) -> User:
    return User(
        id=row[0], org_id=row[1], email=row[2], display_name=row[3],
        status=row[4], created_at=row[5],
    )


def _membership(row: tuple[Any, ...]) -> Membership:
    return Membership(id=row[0], org_id=row[1], user_id=row[2], role=row[3], created_at=row[4])


def _team(row: tuple[Any, ...]) -> Team:
    return Team(id=row[0], org_id=row[1], slug=row[2], name=row[3], created_at=row[4])


def _project(row: tuple[Any, ...]) -> Project:
    return Project(
        id=row[0], org_id=row[1], team_id=row[2], slug=row[3], name=row[4], created_at=row[5]
    )
