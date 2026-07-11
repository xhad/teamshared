"""Bearer middleware behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import BearerAuthMiddleware, current_agent, principal_state_id
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.identity.principal import Principal

DEFAULT_ORG = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _agent_principal(agent: str = "cursor") -> Principal:
    return Principal(
        org_id=DEFAULT_ORG,
        type="agent",
        id=AGENT_ID,
        display=agent,
        roles=("agent",),
    )


def _mock_resolver(*, on_resolve: Principal | None = None) -> MagicMock:
    resolver = MagicMock(spec=PrincipalResolver)
    resolver.resolve = AsyncMock(return_value=on_resolve)
    resolver.anonymous = AsyncMock(return_value=_agent_principal("anonymous"))
    return resolver


def _build_app(resolver: MagicMock, *, disabled: bool = False) -> Starlette:
    async def whoami(request: Request) -> JSONResponse:
        ident = current_agent()
        return JSONResponse({"agent": ident.agent if ident else None})

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp/whoami", whoami, methods=["GET"]),
        ],
        middleware=[
            Middleware(
                BearerAuthMiddleware,
                resolver=resolver,
                auth_disabled=disabled,
            )
        ],
    )


def test_middleware_rejects_missing_header() -> None:
    resolver = _mock_resolver()
    app = _build_app(resolver)
    with TestClient(app) as client:
        resp = client.get("/mcp/whoami")
        assert resp.status_code == 401
        assert resp.json() == {"error": "missing_bearer_token"}


def test_middleware_rejects_unknown_token() -> None:
    resolver = _mock_resolver(on_resolve=None)
    app = _build_app(resolver)
    with TestClient(app) as client:
        resp = client.get(
            "/mcp/whoami", headers={"Authorization": "Bearer bogus"}
        )
        assert resp.status_code == 401


def test_middleware_binds_tsk_principal() -> None:
    resolver = _mock_resolver(on_resolve=_agent_principal("cursor"))
    app = _build_app(resolver)
    with TestClient(app) as client:
        resp = client.get(
            "/mcp/whoami",
            headers={"Authorization": "Bearer tsk_abcd0123secret"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"agent": "cursor"}


def test_health_is_anonymous() -> None:
    resolver = _mock_resolver()
    app = _build_app(resolver)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_public_route_skips_bearer_per_route_policy() -> None:
    """Paths classified as non-MCP must not hit BearerAuthMiddleware."""
    resolver = _mock_resolver(on_resolve=None)
    app = _build_app(resolver)
    with TestClient(app) as client:
        # /health is HEALTH_METRICS in route_policy — no bearer, no 401.
        assert client.get("/health").status_code == 200


def test_mcp_route_requires_bearer_per_route_policy() -> None:
    resolver = _mock_resolver(on_resolve=None)
    app = _build_app(resolver)
    with TestClient(app) as client:
        resp = client.get("/mcp/whoami")
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_bearer_token"


def test_auth_disabled_skips_check() -> None:
    resolver = _mock_resolver()
    app = _build_app(resolver, disabled=True)
    with TestClient(app) as client:
        resp = client.get("/mcp/whoami")
        assert resp.status_code == 200
        assert resp.json() == {"agent": "anonymous"}


def test_principal_state_id_isolates_api_keys() -> None:
    key_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    key_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    org = DEFAULT_ORG
    p_a = Principal(org_id=org, type="agent", id=org, api_key_id=key_a, display="cursor")
    p_b = Principal(org_id=org, type="agent", id=org, api_key_id=key_b, display="codex")
    assert principal_state_id(p_a) == f"p:agent:key:{key_a}"
    assert principal_state_id(p_b) == f"p:agent:key:{key_b}"
    assert principal_state_id(p_a) != principal_state_id(p_b)


def test_principal_state_id_user_uses_user_id() -> None:
    user_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    p = Principal(org_id=DEFAULT_ORG, type="user", id=user_id, display="chad@example.com")
    assert principal_state_id(p) == f"p:user:{user_id}"


async def test_middleware_state_id_uses_api_key() -> None:
    key_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    principal = Principal(
        org_id=DEFAULT_ORG,
        type="agent",
        id=DEFAULT_ORG,
        api_key_id=key_id,
        display="cursor",
        roles=("agent",),
    )
    resolver = _mock_resolver(on_resolve=principal)

    async def state_probe(request: Request) -> JSONResponse:
        ident = current_agent()
        return JSONResponse({"state_id": ident.state_id if ident else None})

    app = Starlette(
        routes=[Route("/mcp/state", state_probe, methods=["GET"])],
        middleware=[Middleware(BearerAuthMiddleware, resolver=resolver, auth_disabled=False)],
    )
    with TestClient(app) as client:
        resp = client.get("/mcp/state", headers={"Authorization": "Bearer tsk_test"})
        assert resp.status_code == 200
        assert resp.json()["state_id"] == f"p:agent:key:{key_id}"
