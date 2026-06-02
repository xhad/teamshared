"""PrincipalResolver contract (mocked stores, no Postgres)."""

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


async def test_agent_provisioning_is_idempotent_and_cached() -> None:
    resolver, upserts, roles = _resolver()

    p1 = await resolver.for_agent("cursor")
    p2 = await resolver.for_agent("cursor")

    assert p1.id == p2.id == AGENT_ID
    assert upserts[0] == 1
    roles.bind_role.assert_awaited_once()


async def test_distinct_agents_provision_separately() -> None:
    resolver, upserts, _ = _resolver()

    await resolver.for_agent("cursor")
    await resolver.for_agent("hermes")

    assert upserts[0] == 2


async def test_api_key_short_circuits() -> None:
    resolver, upserts, _ = _resolver()
    key_principal = Principal(
        org_id=uuid.uuid4(), type="api_key", id=uuid.uuid4(), display="ci-bot"
    )
    resolver.api_keys.authenticate = AsyncMock(return_value=key_principal)

    principal = await resolver.resolve("tsk_live_xyz")

    assert principal is key_principal
    assert upserts[0] == 0


async def test_unknown_token_is_none() -> None:
    resolver, _, _ = _resolver()

    assert await resolver.resolve("garbage") is None


async def test_anonymous_uses_anonymous_agent_name() -> None:
    resolver, _, _ = _resolver()

    principal = await resolver.anonymous()

    assert principal.display == ANONYMOUS_AGENT
    assert principal.org_id == DEFAULT_ORG
