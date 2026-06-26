"""Audit trail for MCP ``agent=`` write attribution overrides."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from teamshared.identity.principal import Principal
from teamshared.memory.facade import MemoryFacade

ORG = UUID("00000000-0000-0000-0000-000000000001")
CALLER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = UUID("22222222-2222-2222-2222-222222222222")
HERMES_ID = UUID("33333333-3333-3333-3333-333333333333")


def _caller() -> Principal:
    return Principal(
        org_id=ORG,
        type="agent",
        id=CALLER_ID,
        display="cursor",
        roles=("agent",),
    )


def _facade(*, override: Principal) -> MemoryFacade:
    resolver = MagicMock()
    resolver.for_agent = AsyncMock(return_value=override)
    audit = MagicMock()
    audit.record = AsyncMock()
    services = MagicMock()
    services.tenant_db = MagicMock()
    services.authorizer = MagicMock(return_value=MagicMock())
    services.audit = audit
    return MemoryFacade(
        services=services,
        resolver=resolver,
        working=MagicMock(),
        agent_state=MagicMock(),
        procedural=MagicMock(),
        skills=MagicMock(),
        strategic=MagicMock(),
        graph=None,
    )


async def test_no_audit_when_agent_override_matches_caller() -> None:
    facade = _facade(override=_caller())
    caller = _caller()

    writer = await facade._write_principal(caller, "cursor", operation="remember")

    assert writer is caller
    facade.services.audit.record.assert_not_awaited()


async def test_audit_when_override_applied() -> None:
    hermes = Principal(
        org_id=ORG,
        type="agent",
        id=HERMES_ID,
        display="hermes",
        roles=("agent",),
    )
    facade = _facade(override=hermes)
    caller = _caller()

    writer = await facade._write_principal(
        caller, "hermes", operation="remember", request_id="req-1"
    )

    assert writer.display == "hermes"
    facade.services.audit.record.assert_awaited_once()
    kwargs = facade.services.audit.record.await_args.kwargs
    assert kwargs["action"] == "memory.agent_override"
    assert kwargs["payload"]["applied"] is True
    assert kwargs["payload"]["requested_agent"] == "hermes"
    assert kwargs["payload"]["attributed_agent"] == "hermes"
    assert kwargs["payload"]["operation"] == "remember"
    assert kwargs["request_id"] == "req-1"


async def test_override_is_free_text_label_keeping_caller_identity() -> None:
    # Attribution is a free-text label: the override only changes the display
    # name, never the caller's org / identity / RBAC. There is no agents
    # registry and therefore no cross-org rejection path.
    facade = _facade(override=_caller())
    caller = _caller()

    writer = await facade._write_principal(caller, "hermes", operation="procedure_set")

    assert writer is not caller
    assert writer.display == "hermes"
    assert writer.org_id == caller.org_id
    assert writer.id == caller.id
    assert writer.roles == caller.roles
    kwargs = facade.services.audit.record.await_args.kwargs
    assert kwargs["payload"]["applied"] is True
    assert kwargs["payload"]["attributed_agent"] == "hermes"
