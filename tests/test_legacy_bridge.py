"""G2 identity bridge: legacy bearer tokens -> default-org agent Principals.

`PrincipalResolver` is the single seam the MCP `BearerAuthMiddleware` uses to
turn any presented token into a `Principal`. These tests pin its contract with
mocked stores (no Postgres):

- `tsk_` API keys and JWT sessions short-circuit to their real Principal.
- A legacy token maps to a synthetic *agent* Principal in the default org.
- Agent provisioning is idempotent and cached (one upsert per agent/org).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from teamshared.identity.legacy_bridge import ANONYMOUS_AGENT, PrincipalResolver
from teamshared.identity.principal import Principal

DEFAULT_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Conn:
    def __init__(self, agent_id: uuid.UUID, counter: list[int]) -> None:
        self._agent_id = agent_id
        self._counter = counter

    async def execute(self, sql: str, params: object = None):
        self._counter[0] += 1
        cur = MagicMock()
        cur.fetchone = AsyncMock(return_value=(self._agent_id,))
        return cur


class _OrgCM:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _resolver() -> tuple[PrincipalResolver, list[int], MagicMock]:
    upserts = [0]
    tenant_db = MagicMock()
    tenant_db.org = MagicMock(return_value=_OrgCM(_Conn(AGENT_ID, upserts)))
    roles = MagicMock()
    roles.bind_role = AsyncMock()
    api_keys = MagicMock()
    api_keys.authenticate = AsyncMock(return_value=None)
    resolver = PrincipalResolver(
        api_keys=api_keys,
        roles=roles,
        tenant_db=tenant_db,
        default_org_id=DEFAULT_ORG,
        session_secret=None,
    )
    return resolver, upserts, roles


async def test_legacy_token_maps_to_default_org_agent_principal() -> None:
    resolver, _, roles = _resolver()

    principal = await resolver.resolve("teamshared_abc123", legacy_agent="cursor")

    assert principal is not None
    assert principal.org_id == DEFAULT_ORG
    assert principal.type == "agent"
    assert principal.id == AGENT_ID
    assert principal.display == "cursor"
    assert principal.roles == ("agent",)
    # First use binds the baseline agent role.
    roles.bind_role.assert_awaited_once()


async def test_agent_provisioning_is_idempotent_and_cached() -> None:
    resolver, upserts, roles = _resolver()

    p1 = await resolver.for_agent("cursor")
    p2 = await resolver.for_agent("cursor")

    assert p1.id == p2.id == AGENT_ID
    # Second lookup hits the in-process cache: no extra DB upsert or role bind.
    assert upserts[0] == 1
    roles.bind_role.assert_awaited_once()


async def test_distinct_agents_provision_separately() -> None:
    resolver, upserts, _ = _resolver()

    await resolver.for_agent("cursor")
    await resolver.for_agent("hermes")

    assert upserts[0] == 2


async def test_api_key_short_circuits_before_legacy() -> None:
    resolver, upserts, _ = _resolver()
    key_principal = Principal(
        org_id=uuid.uuid4(), type="api_key", id=uuid.uuid4(), display="ci-bot"
    )
    resolver.api_keys.authenticate = AsyncMock(return_value=key_principal)

    principal = await resolver.resolve("tsk_live_xyz", legacy_agent="cursor")

    assert principal is key_principal
    # Legacy provisioning never ran.
    assert upserts[0] == 0


async def test_unknown_token_without_legacy_agent_is_none() -> None:
    resolver, _, _ = _resolver()

    assert await resolver.resolve("garbage", legacy_agent=None) is None


async def test_anonymous_uses_anonymous_agent_name() -> None:
    resolver, _, _ = _resolver()

    principal = await resolver.anonymous()

    assert principal.display == ANONYMOUS_AGENT
    assert principal.org_id == DEFAULT_ORG
