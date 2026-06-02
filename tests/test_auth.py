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

from teamshared.auth import BearerAuthMiddleware, current_agent
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


def test_auth_disabled_skips_check() -> None:
    resolver = _mock_resolver()
    app = _build_app(resolver, disabled=True)
    with TestClient(app) as client:
        resp = client.get("/mcp/whoami")
        assert resp.status_code == 200
        assert resp.json() == {"agent": "anonymous"}
