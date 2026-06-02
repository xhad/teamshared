"""MemoryService must enforce RBAC via RequestContext.authorizer, not a stale instance."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from teamshared.identity.principal import Principal
from teamshared.identity.rbac import Permissions
from teamshared.memory.request_context import RequestContext
from teamshared.memory.service import MemoryService

ORG = UUID("00000000-0000-0000-0000-000000000001")
PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")
MEMORY_ID = UUID("22222222-2222-2222-2222-222222222222")


def _principal() -> Principal:
    return Principal(
        org_id=ORG,
        type="agent",
        id=PRINCIPAL_ID,
        display="cursor",
        roles=("agent",),
    )


async def test_delete_uses_ctx_authorizer() -> None:
    ctx_authorizer = MagicMock()
    ctx_authorizer.require = AsyncMock()

    stale_authorizer = MagicMock()
    stale_authorizer.require = AsyncMock(
        side_effect=AssertionError("must not use a process-wide authorizer")
    )

    vector_store = MagicMock()
    vector_store.soft_delete = AsyncMock(return_value=True)
    audit = MagicMock()
    audit.record = AsyncMock()

    service = MemoryService(vector_store, audit)
    ctx = RequestContext(
        principal=_principal(),
        db=MagicMock(),
        authorizer=ctx_authorizer,
    )

    ok = await service.delete(ctx, MEMORY_ID)

    assert ok is True
    ctx_authorizer.require.assert_awaited_once_with(
        ctx.principal, Permissions.MEMORY_DELETE
    )
    stale_authorizer.require.assert_not_awaited()
