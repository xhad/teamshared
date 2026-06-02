"""Bridge the legacy bearer-token identity onto org-scoped Principals.

G2 rebinds the MCP tool surface onto the same org-scoped :class:`Principal`
model the ``/v1`` REST API uses. This resolver is the single entry point the
MCP ``BearerAuthMiddleware`` calls to turn any presented token into a
Principal, in priority order:

1. A hashed ``tsk_`` API key -> its real Principal (any org).
2. A signed dashboard session JWT -> the user Principal it carries.
3. When ``legacy_agent`` is passed (legacy file auth opt-in via
   ``TEAMSHARED_LEGACY_TOKEN_AUTH_ENABLED``), a synthetic agent Principal in the
   *default org* — auto-provisioned on first use.

The agent-name -> id mapping is cached in-process; the upsert is cheap and
idempotent so a cold cache is harmless.
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

    async def resolve(self, token: str, *, legacy_agent: str | None = None) -> Principal | None:
        """Return the Principal for ``token`` or ``None`` when unauthenticated.

        ``legacy_agent`` is the agent name a legacy token resolved to (from the
        JSON ``TokenStore``); pass it so we don't re-parse the token here.
        """
        principal = await self.api_keys.authenticate(token)
        if principal is not None:
            return principal
        if self.session_secret:
            session_principal = verify_session(token, secret=self.session_secret)
            if session_principal is not None:
                return session_principal
        if legacy_agent is not None:
            return await self.for_agent(legacy_agent)
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
