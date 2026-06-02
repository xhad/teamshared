"""Mint org-scoped ``tsk_`` API keys for harness agent types.

Hashed API keys are bound to a provisioned agent principal in the default org
(or an explicit ``org_id``). Invite redeem and ``teamshared token mint`` use
:class:`AgentTokenMinter`.
"""

from __future__ import annotations

from uuid import UUID

from teamshared.identity.api_keys import ApiKeyStore, MintedKey
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.logging import get_logger

log = get_logger(__name__)


class AgentTokenMinter:
    """Issue a one-time ``tsk_`` bearer for a known agent type name."""

    def __init__(
        self,
        *,
        api_keys: ApiKeyStore,
        resolver: PrincipalResolver,
        org_id: UUID,
    ) -> None:
        self.api_keys = api_keys
        self.resolver = resolver
        self.org_id = org_id

    async def mint(self, agent_type: str) -> tuple[str, str]:
        """Provision ``agent_type`` in ``org_id`` and return ``(agent_type, token)``."""
        principal = await self.resolver.agent_principal(self.org_id, agent_type)
        key = await self.api_keys.mint(
            org_id=principal.org_id,
            principal_type="agent",
            principal_id=principal.id,
            name=f"agent-{agent_type}",
        )
        log.info(
            "agent_api_key_minted",
            agent=agent_type,
            org_id=str(principal.org_id),
            prefix=key.prefix,
        )
        return agent_type, key.token

    async def mint_record(self, agent_type: str) -> tuple[str, MintedKey]:
        """Like :meth:`mint` but also returns the :class:`MintedKey` metadata."""
        principal = await self.resolver.agent_principal(self.org_id, agent_type)
        key = await self.api_keys.mint(
            org_id=principal.org_id,
            principal_type="agent",
            principal_id=principal.id,
            name=f"agent-{agent_type}",
        )
        return agent_type, key
