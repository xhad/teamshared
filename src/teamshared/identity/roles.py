"""Role binding helpers: grant system/custom roles to principals."""

from __future__ import annotations

from uuid import UUID

from teamshared.identity.principal import PrincipalType
from teamshared.tenancy.context import TenantDb


class RoleStore:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def resolve_role_id(self, org_id: UUID, name: str) -> UUID | None:
        """Find a role by name: org-custom first, then the system template."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id FROM roles WHERE name = %s "
                "ORDER BY (org_id IS NOT NULL) DESC LIMIT 1",
                (name,),
            )
            row = await cur.fetchone()
        return row[0] if row else None

    async def bind_role(
        self,
        *,
        org_id: UUID,
        principal_type: PrincipalType,
        principal_id: UUID,
        role_name: str,
        scope_type: str | None = None,
        scope_id: UUID | None = None,
    ) -> bool:
        role_id = await self.resolve_role_id(org_id, role_name)
        if role_id is None:
            raise ValueError(f"unknown role: {role_name!r}")
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO role_bindings "
                "(org_id, principal_type, principal_id, role_id, scope_type, scope_id) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (
                    str(org_id), principal_type, str(principal_id), str(role_id),
                    scope_type, str(scope_id) if scope_id else None,
                ),
            )
            return cur.rowcount > 0

    async def unbind_role(
        self,
        *,
        org_id: UUID,
        principal_type: PrincipalType,
        principal_id: UUID,
        role_name: str,
    ) -> bool:
        """Remove a role binding from a principal. False if it wasn't bound."""
        role_id = await self.resolve_role_id(org_id, role_name)
        if role_id is None:
            return False
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "DELETE FROM role_bindings WHERE principal_type = %s "
                "AND principal_id = %s AND role_id = %s",
                (principal_type, str(principal_id), str(role_id)),
            )
            return cur.rowcount > 0

    async def list_bindings(self, org_id: UUID) -> list[dict[str, object]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT rb.principal_type, rb.principal_id, r.name, rb.scope_type, rb.scope_id "
                "FROM role_bindings rb JOIN roles r ON r.id = rb.role_id "
                "ORDER BY rb.created_at"
            )
            rows = await cur.fetchall()
        return [
            {
                "principal_type": r[0], "principal_id": str(r[1]), "role": r[2],
                "scope_type": r[3], "scope_id": str(r[4]) if r[4] else None,
            }
            for r in rows
        ]
