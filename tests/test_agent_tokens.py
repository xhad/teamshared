"""AgentTokenMinter: legacy mint path issues org-scoped tsk_ keys."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.identity.agent_tokens import AgentTokenMinter
from teamshared.identity.api_keys import MintedKey
from teamshared.identity.legacy_bridge import PrincipalResolver

DEFAULT_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _minter() -> tuple[AgentTokenMinter, MagicMock]:
    tenant_db = MagicMock()
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=MagicMock(fetchone=AsyncMock(return_value=(AGENT_ID,))))
    tenant_db.org = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    roles = MagicMock()
    roles.bind_role = AsyncMock()
    api_keys = MagicMock()
    api_keys.mint = AsyncMock(
        return_value=MintedKey(
            id=uuid.uuid4(),
            prefix="tsk_abcd1234",
            token="tsk_abcd1234_secretpart",
        )
    )
    resolver = PrincipalResolver(
        api_keys=api_keys,
        roles=roles,
        tenant_db=tenant_db,
        default_org_id=DEFAULT_ORG,
    )
    return AgentTokenMinter(api_keys=api_keys, resolver=resolver, org_id=DEFAULT_ORG), api_keys


@pytest.mark.asyncio
async def test_mint_provisions_agent_and_mints_api_key() -> None:
    minter, api_keys = _minter()
    agent_type, token = await minter.mint("cursor")
    assert agent_type == "cursor"
    assert token.startswith("tsk_")
    api_keys.mint.assert_awaited_once()
    call = api_keys.mint.await_args.kwargs
    assert call["org_id"] == DEFAULT_ORG
    assert call["principal_type"] == "agent"
    # Keys are org-bound (no agents registry); the agent type is the label.
    assert call["principal_id"] == DEFAULT_ORG
    assert call["label"] == "cursor"
