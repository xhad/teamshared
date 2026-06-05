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
        # The table's UNIQUE constraint covers (scope_type, scope_id), but Postgres
        # treats NULLs as distinct, so ``ON CONFLICT DO NOTHING`` never fires for
        # org-wide (NULL scope) bindings and duplicates accumulate. Guard the insert
        # with NOT EXISTS using IS NOT DISTINCT FROM so NULL scopes dedupe too.
        scope_id_s = str(scope_id) if scope_id else None
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO role_bindings "
                "(org_id, principal_type, principal_id, role_id, scope_type, scope_id) "
                "SELECT %s, %s, %s, %s, %s, %s WHERE NOT EXISTS ("
                "  SELECT 1 FROM role_bindings WHERE org_id = %s "
                "  AND principal_type = %s AND principal_id = %s AND role_id = %s "
                "  AND scope_type IS NOT DISTINCT FROM %s "
                "  AND scope_id IS NOT DISTINCT FROM %s)",
                (
                    str(org_id), principal_type, str(principal_id), str(role_id),
                    scope_type, scope_id_s,
                    str(org_id), principal_type, str(principal_id), str(role_id),
                    scope_type, scope_id_s,
                ),
            )
            return cur.rowcount > 0

    async def set_user_role(
        self, *, org_id: UUID, principal_id: UUID, role_name: str
    ) -> None:
        """Make ``role_name`` the user's sole org-wide system role binding.

        Replaces any existing org-wide (NULL scope) system-role bindings so the
        member ends up with exactly one effective role and no duplicate rows.
        """
        role_id = await self.resolve_role_id(org_id, role_name)
        if role_id is None:
            raise ValueError(f"unknown role: {role_name!r}")
        async with self.db.org(org_id) as conn:
            await conn.execute(
                "DELETE FROM role_bindings rb USING roles r "
                "WHERE rb.role_id = r.id AND r.is_system "
                "AND rb.principal_type = 'user' AND rb.principal_id = %s "
                "AND rb.scope_type IS NULL AND rb.scope_id IS NULL",
                (str(principal_id),),
            )
            await conn.execute(
                "INSERT INTO role_bindings "
                "(org_id, principal_type, principal_id, role_id) "
                "VALUES (%s, 'user', %s, %s)",
                (str(org_id), str(principal_id), str(role_id)),
            )

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
