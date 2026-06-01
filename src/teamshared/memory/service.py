"""Permission-checked, audited memory operations shared by REST + MCP.

Reads go through :class:`~teamshared.memory.retrieval.SecureRetrieval`; this
service covers the single-item mutations (get/update/delete/share) so the
permission check and audit event live in exactly one place regardless of which
transport invoked them.
"""

from __future__ import annotations

from uuid import UUID

from teamshared.identity.rbac import Authorizer, Permissions
from teamshared.memory.audit import AuditLog
from teamshared.memory.request_context import RequestContext
from teamshared.memory.types import MemoryItem
from teamshared.memory.vectorstore import VectorStore


class MemoryService:
    def __init__(self, vector_store: VectorStore, audit: AuditLog, authorizer: Authorizer) -> None:
        self.vector_store = vector_store
        self.audit = audit
        self.authorizer = authorizer

    async def get(self, ctx: RequestContext, memory_id: UUID) -> MemoryItem | None:
        await self.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        item = await self.vector_store.get(ctx.org_id, memory_id)
        if item is not None:
            await self.audit.record(
                agent=ctx.principal.attribution, action="memory.read_item",
                org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
                resource_type="memory", target_id=str(memory_id), request_id=ctx.request_id,
            )
        return item

    async def update(self, ctx: RequestContext, memory_id: UUID, content: str) -> bool:
        await self.authorizer.require(ctx.principal, Permissions.MEMORY_UPDATE)
        ok = await self.vector_store.update_content(
            ctx.org_id, memory_id, content=content, editor_id=ctx.principal.id
        )
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.update",
            org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
            resource_type="memory", target_id=str(memory_id), request_id=ctx.request_id,
            after={"updated": ok},
        )
        return ok

    async def delete(self, ctx: RequestContext, memory_id: UUID) -> bool:
        await self.authorizer.require(ctx.principal, Permissions.MEMORY_DELETE)
        ok = await self.vector_store.soft_delete(ctx.org_id, memory_id)
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.delete",
            org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
            resource_type="memory", target_id=str(memory_id), request_id=ctx.request_id,
            after={"deleted": ok},
        )
        return ok

    async def share(
        self,
        ctx: RequestContext,
        memory_id: UUID,
        *,
        target_scope: str,
        target_id: UUID | None,
    ) -> bool:
        await self.authorizer.require(ctx.principal, Permissions.MEMORY_SHARE)
        async with ctx.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO memory_shares (org_id, memory_id, target_scope, target_id, granted_by) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    str(ctx.org_id), str(memory_id), target_scope,
                    str(target_id) if target_id else None, str(ctx.principal.id),
                ),
            )
            # Flag the item shared so visibility filters surface it.
            await conn.execute(
                "UPDATE memory_items SET visibility = 'shared', updated_at = now() WHERE id = %s",
                (str(memory_id),),
            )
            ok = cur.rowcount > 0
        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.share",
            org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
            resource_type="memory", target_id=str(memory_id), request_id=ctx.request_id,
            after={"target_scope": target_scope, "target_id": str(target_id) if target_id else None},
        )
        return ok
