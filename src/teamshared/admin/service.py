"""Admin and user-facing controls backing the dashboard."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from teamshared.identity.principal import PrincipalType
from teamshared.identity.rbac import Permissions
from teamshared.identity.roles import RoleStore
from teamshared.memory.audit import AuditLog
from teamshared.memory.request_context import RequestContext
from teamshared.tenancy.context import TenantDb


class AdminService:
    def __init__(self, db: TenantDb, roles: RoleStore, audit: AuditLog) -> None:
        self.db = db
        self.roles = roles
        self.audit = audit

    async def list_members(self, ctx: RequestContext) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT u.id, u.email, u.display_name, m.role, u.status "
                "FROM users u JOIN memberships m ON m.user_id = u.id ORDER BY u.created_at"
            )
            rows = await cur.fetchall()
        return [
            {"user_id": str(r[0]), "email": r[1], "display_name": r[2], "role": r[3], "status": r[4]}
            for r in rows
        ]

    async def add_member(
        self, ctx: RequestContext, *, email: str, role: str = "member"
    ) -> dict[str, Any]:
        """Add an email to this org: upsert global account + per-org user +
        membership + RBAC role. Idempotent; re-activates an existing member.

        The added email can then sign in with an OTP and switch into this org.
        """
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        email_l = email.strip().lower()
        if not email_l:
            raise ValueError("email is required")
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT id FROM provision_account(%s, %s)", (email_l, None)
            )
            arow = await cur.fetchone()
        account_id = arow[0] if arow else None
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO users (org_id, email, account_id) VALUES (%s, %s, %s) "
                "ON CONFLICT (org_id, email) DO UPDATE SET status = 'active', "
                "  account_id = COALESCE(EXCLUDED.account_id, users.account_id), "
                "  updated_at = now() "
                "RETURNING id",
                (str(ctx.org_id), email_l, str(account_id) if account_id else None),
            )
            urow = await cur.fetchone()
            assert urow is not None
            user_id: UUID = urow[0]
            await conn.execute(
                "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, %s) "
                "ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role",
                (str(ctx.org_id), str(user_id), role),
            )
        await self.roles.bind_role(
            org_id=ctx.org_id, principal_type="user", principal_id=user_id, role_name=role
        )
        await self.audit.record(
            agent=ctx.principal.attribution, action="member.add", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="user",
            target_id=str(user_id), request_id=ctx.request_id,
            after={"email": email_l, "role": role},
        )
        return {"user_id": str(user_id), "email": email_l, "role": role}

    async def grant_role(
        self,
        ctx: RequestContext,
        *,
        principal_type: PrincipalType,
        principal_id: UUID,
        role_name: str,
    ) -> bool:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        ok = await self.roles.bind_role(
            org_id=ctx.org_id, principal_type=principal_type,
            principal_id=principal_id, role_name=role_name,
        )
        await self.audit.record(
            agent=ctx.principal.attribution, action="rbac.grant_role", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="role_binding",
            target_id=str(principal_id), request_id=ctx.request_id,
            after={"role": role_name, "principal_type": principal_type},
        )
        return ok

    async def list_role_bindings(self, ctx: RequestContext) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        return await self.roles.list_bindings(ctx.org_id)

    async def revoke_role(
        self,
        ctx: RequestContext,
        *,
        principal_type: PrincipalType,
        principal_id: UUID,
        role_name: str,
    ) -> bool:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        ok = await self.roles.unbind_role(
            org_id=ctx.org_id, principal_type=principal_type,
            principal_id=principal_id, role_name=role_name,
        )
        await self.audit.record(
            agent=ctx.principal.attribution, action="rbac.revoke_role", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="role_binding",
            target_id=str(principal_id), request_id=ctx.request_id,
            before={"role": role_name, "principal_type": principal_type},
        )
        return ok

    async def create_agent(
        self, ctx: RequestContext, *, name: str, kind: str = "agent"
    ) -> UUID:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO agents (org_id, name, kind) VALUES (%s,%s,%s) RETURNING id",
                (str(ctx.org_id), name, kind),
            )
            row = await cur.fetchone()
        assert row is not None
        agent_id: UUID = row[0]
        # New agents get the baseline 'agent' role so their keys can read/create.
        await self.roles.bind_role(
            org_id=ctx.org_id, principal_type="agent", principal_id=agent_id, role_name="agent"
        )
        return agent_id

    async def list_agents(self, ctx: RequestContext) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT id, name, kind, status, created_at FROM agents ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [
            {"id": str(r[0]), "name": r[1], "kind": r[2], "status": r[3],
             "created_at": r[4].isoformat() if r[4] else None}
            for r in rows
        ]

    async def set_agent_status(
        self, ctx: RequestContext, agent_id: UUID, status: str
    ) -> bool:
        """Enable or disable an agent identity. ``status`` in {active, disabled}."""
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        if status not in {"active", "disabled"}:
            raise ValueError(f"invalid agent status: {status!r}")
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "UPDATE agents SET status = %s WHERE id = %s",
                (status, str(agent_id)),
            )
            changed = cur.rowcount > 0
        await self.audit.record(
            agent=ctx.principal.attribution, action="agent.set_status", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="agent",
            target_id=str(agent_id), request_id=ctx.request_id, after={"status": status},
        )
        return changed

    async def create_retention_policy(
        self,
        ctx: RequestContext,
        *,
        name: str,
        max_age_days: int | None,
        max_items: int | None,
        kinds: list[str] | None,
    ) -> UUID:
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_ADMIN)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO retention_policies (org_id, name, max_age_days, max_items, kinds) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (str(ctx.org_id), name, max_age_days, max_items, kinds or []),
            )
            row = await cur.fetchone()
        assert row is not None
        policy_id: UUID = row[0]
        return policy_id

    async def list_retention_policies(self, ctx: RequestContext) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_ADMIN)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT id, name, max_age_days, max_items, kinds FROM retention_policies "
                "ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [
            {"id": str(r[0]), "name": r[1], "max_age_days": r[2], "max_items": r[3],
             "kinds": list(r[4] or [])}
            for r in rows
        ]

    async def export_memory(self, ctx: RequestContext) -> dict[str, Any]:
        """GDPR/portability: dump the org's active memory items."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_EXPORT)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT id, kind, scope, visibility, content, subject, tags, source, "
                "created_at FROM memory_items WHERE status = 'active' ORDER BY created_at"
            )
            rows = await cur.fetchall()
        items = [
            {
                "id": str(r[0]), "kind": r[1], "scope": r[2], "visibility": r[3],
                "content": r[4], "subject": r[5], "tags": list(r[6] or []), "source": r[7],
                "created_at": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.export", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="org",
            request_id=ctx.request_id, after={"count": len(items)},
        )
        return {"org_id": str(ctx.org_id), "count": len(items), "items": items}

    async def purge_user_memory(self, ctx: RequestContext, user_id: UUID) -> int:
        """GDPR hard-delete: remove memory owned by a user."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_ADMIN)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "DELETE FROM memory_items WHERE owner_type = 'user' AND owner_id = %s",
                (str(user_id),),
            )
            deleted = cur.rowcount
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.purge_user", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="user",
            target_id=str(user_id), request_id=ctx.request_id,
            before={"deleted_estimate": deleted}, best_effort=False,
        )
        return deleted

    @staticmethod
    def export_to_json(export: dict[str, Any]) -> str:
        return json.dumps(export, indent=2)
