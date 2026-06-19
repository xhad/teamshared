"""Admin and user-facing controls backing the dashboard."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from teamshared.admin.exceptions import (
    ExportTooLargeError,
    SelfErasureBlockedError,
    UserNotInOrgError,
)
from teamshared.identity.principal import PrincipalType
from teamshared.identity.rbac import Permissions
from teamshared.identity.roles import RoleStore
from teamshared.memory.audit import AuditLog
from teamshared.memory.request_context import RequestContext
from teamshared.metrics import METRICS
from teamshared.tenancy.context import TenantDb

_EXPORT_SCHEMA_VERSION = 1


class AdminService:
    def __init__(
        self,
        db: TenantDb,
        roles: RoleStore,
        audit: AuditLog,
        *,
        export_max_items: int = 50_000,
    ) -> None:
        self.db = db
        self.roles = roles
        self.audit = audit
        self.export_max_items = export_max_items

    async def _fetch_members(self, org_id: UUID) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT u.id, u.email, u.display_name, m.role, u.status "
                "FROM users u JOIN memberships m ON m.user_id = u.id ORDER BY u.created_at"
            )
            rows = await cur.fetchall()
        return [
            {"user_id": str(r[0]), "email": r[1], "display_name": r[2], "role": r[3], "status": r[4]}
            for r in rows
        ]

    async def list_members(self, ctx: RequestContext) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        return await self._fetch_members(ctx.org_id)

    async def list_members_for_erasure(self, ctx: RequestContext) -> list[dict[str, Any]]:
        """Member directory for the console erasure UI (``memory:admin``)."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_ADMIN)
        return await self._fetch_members(ctx.org_id)

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
        if principal_type == "user":
            # A user has exactly one role: keep the RBAC binding and the
            # membership row in sync so the People list reflects the change.
            await self.roles.set_user_role(
                org_id=ctx.org_id, principal_id=principal_id, role_name=role_name
            )
            async with self.db.org(ctx.org_id) as conn:
                await conn.execute(
                    "UPDATE memberships SET role = %s "
                    "WHERE org_id = %s AND user_id = %s",
                    (role_name, str(ctx.org_id), str(principal_id)),
                )
            ok = True
        else:
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
        self,
        ctx: RequestContext,
        *,
        name: str,
        kind: str = "agent",
        runtime: str = "user",
    ) -> UUID:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        if runtime not in {"user", "cloud"}:
            raise ValueError(f"invalid agent runtime: {runtime!r}")
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO agents (org_id, name, kind, runtime) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (str(ctx.org_id), name, kind, runtime),
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
                "SELECT id, name, kind, status, created_at, runtime "
                "FROM agents ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [
            {"id": str(r[0]), "name": r[1], "kind": r[2], "status": r[3],
             "created_at": r[4].isoformat() if r[4] else None,
             "runtime": r[5]}
            for r in rows
        ]

    async def set_agent_runtime(
        self, ctx: RequestContext, agent_id: UUID, runtime: str
    ) -> bool:
        """Switch an agent between ``user`` (local/MCP) and ``cloud`` (server-run)."""
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        if runtime not in {"user", "cloud"}:
            raise ValueError(f"invalid agent runtime: {runtime!r}")
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "UPDATE agents SET runtime = %s WHERE id = %s",
                (runtime, str(agent_id)),
            )
        return cur.rowcount > 0

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

    async def _assert_org_member(self, org_id: UUID, user_id: UUID) -> None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT 1 FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE u.id = %s AND u.status = 'active' LIMIT 1",
                (str(user_id),),
            )
            row = await cur.fetchone()
        if row is None:
            raise UserNotInOrgError(user_id)

    async def export_memory(self, ctx: RequestContext) -> dict[str, Any]:
        """GDPR/portability: dump active semantic/episodic items and procedures."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_EXPORT)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE status = 'active'"
            )
            count_row = await cur.fetchone()
            total = int(count_row[0]) if count_row else 0
            if total > self.export_max_items:
                raise ExportTooLargeError(total, self.export_max_items)
            cur = await conn.execute(
                "SELECT id, pillar, kind, scope, visibility, content, subject, tags, "
                "source, owner_type, owner_id, created_at, updated_at "
                "FROM memory_items WHERE status = 'active' ORDER BY created_at"
            )
            rows = await cur.fetchall()
            cur = await conn.execute(
                "SELECT name, version, description, steps_md, tool_recipe, tags, "
                "created_by, created_at, status FROM procedures "
                "WHERE status = 'active' ORDER BY name, version"
            )
            proc_rows = await cur.fetchall()
        items = [
            {
                "id": str(r[0]), "pillar": r[1], "kind": r[2], "scope": r[3],
                "visibility": r[4], "content": r[5], "subject": r[6],
                "tags": list(r[7] or []), "source": r[8],
                "owner_type": r[9], "owner_id": str(r[10]) if r[10] else None,
                "created_at": r[11].isoformat() if r[11] else None,
                "updated_at": r[12].isoformat() if r[12] else None,
            }
            for r in rows
        ]
        procedures = [
            {
                "name": r[0], "version": r[1], "description": r[2], "steps_md": r[3],
                "tool_recipe": r[4], "tags": list(r[5] or []), "created_by": r[6],
                "created_at": r[7].isoformat() if r[7] else None, "status": r[8],
            }
            for r in proc_rows
        ]
        exported_at = datetime.now(UTC).isoformat()
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.export", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="org",
            request_id=ctx.request_id,
            after={
                "memory_items": len(items),
                "procedures": len(procedures),
                "exported_at": exported_at,
            },
        )
        METRICS.admin_export_total.inc()
        return {
            "schema_version": _EXPORT_SCHEMA_VERSION,
            "org_id": str(ctx.org_id),
            "exported_at": exported_at,
            "exported_by": ctx.principal.attribution,
            "memory_items": items,
            "procedures": procedures,
            "counts": {"memory_items": len(items), "procedures": len(procedures)},
        }

    async def purge_user_memory(self, ctx: RequestContext, user_id: UUID) -> int:
        """GDPR erasure: soft-delete memory owned by or scoped to a user."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_ADMIN)
        if ctx.principal.type == "user" and ctx.principal.id == user_id:
            raise SelfErasureBlockedError()
        await self._assert_org_member(ctx.org_id, user_id)
        uid = str(user_id)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "UPDATE memory_items SET status = 'soft_deleted', deleted_at = now(), "
                "updated_at = now() WHERE status != 'soft_deleted' AND ("
                "  (owner_type = 'user' AND owner_id = %s) "
                "  OR (scope = 'user' AND scope_ref_id = %s)"
                ")",
                (uid, uid),
            )
            deleted = cur.rowcount
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.purge_user", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="user",
            target_id=uid, request_id=ctx.request_id,
            after={"soft_deleted": deleted, "mode": "soft_delete"},
            best_effort=False,
        )
        METRICS.admin_purge_total.inc()
        return deleted

    @staticmethod
    def export_to_json(export: dict[str, Any]) -> str:
        return json.dumps(export, indent=2)
