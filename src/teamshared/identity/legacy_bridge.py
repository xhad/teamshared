"""Resolve bearer tokens to org-scoped :class:`~teamshared.identity.principal.Principal`.

The MCP ``BearerAuthMiddleware`` and related surfaces call :class:`PrincipalResolver`
to authenticate presented tokens, in priority order:

1. A hashed ``tsk_`` API key → its bound Principal (any org).
2. A signed console session JWT → the user Principal it carries.

:class:`PrincipalResolver.for_agent` / :meth:`anonymous` synthesize agent
Principals in the default org (used when ``auth_disabled`` is set).
"""

from __future__ import annotations

from uuid import UUID

from teamshared.identity.api_keys import ApiKeyStore
from teamshared.identity.principal import Principal
from teamshared.identity.roles import RoleStore
from teamshared.identity.sessions import verify_session
from teamshared.logging import get_logger
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

ANONYMOUS_AGENT = "anonymous"


class PrincipalResolver:
    """Resolve any presented token (or the anonymous identity) to a Principal."""

    def __init__(
        self,
        *,
        api_keys: ApiKeyStore,
        roles: RoleStore,
        tenant_db: TenantDb,
        default_org_id: UUID,
        session_secret: str | None = None,
    ) -> None:
        self.api_keys = api_keys
        self.roles = roles
        self.tenant_db = tenant_db
        self.default_org_id = default_org_id
        self.session_secret = session_secret
        self._agent_cache: dict[str, UUID] = {}

    async def resolve(self, token: str) -> Principal | None:
        """Return the Principal for ``token`` or ``None`` when unauthenticated."""
        principal = await self.api_keys.authenticate(token)
        if principal is not None:
            return principal
        if self.session_secret:
            session_principal = verify_session(token, secret=self.session_secret)
            if session_principal is not None:
                return session_principal
        return None

    async def for_agent(self, agent: str) -> Principal:
        """Synthesize an agent Principal in the default org, provisioning as needed."""
        return await self.agent_principal(self.default_org_id, agent)

    async def agent_principal(self, org_id: UUID, agent: str) -> Principal:
        """Synthesize an agent Principal in ``org_id`` (provisioning + role bind)."""
        agent_id = await self._ensure_agent(agent, org_id)
        return Principal(
            org_id=org_id,
            type="agent",
            id=agent_id,
            display=agent,
            roles=("agent",),
        )

    async def anonymous(self) -> Principal:
        """Principal used when ``auth_disabled`` is set (local dev / tests)."""
        return await self.for_agent(ANONYMOUS_AGENT)

    async def _ensure_agent(self, name: str, org_id: UUID) -> UUID:
        cache_key = f"{org_id}:{name}"
        cached = self._agent_cache.get(cache_key)
        if cached is not None:
            return cached
        async with self.tenant_db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO agents (org_id, name, kind) VALUES (%s, %s, 'agent') "
                "ON CONFLICT (org_id, name) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id",
                (str(org_id), name),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError(f"failed to provision agent {name!r} in org {org_id}")
        agent_id: UUID = row[0]
        # Idempotent: a returning agent already holds the role.
        await self.roles.bind_role(
            org_id=org_id,
            principal_type="agent",
            principal_id=agent_id,
            role_name="agent",
        )
        self._agent_cache[cache_key] = agent_id
        return agent_id
