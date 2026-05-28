"""Token store + bearer middleware behaviour."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import BearerAuthMiddleware, TokenStore, current_agent


def _build_app(store: TokenStore, *, disabled: bool = False) -> Starlette:
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
        middleware=[Middleware(BearerAuthMiddleware, store=store, auth_disabled=disabled)],
    )


def test_token_store_mint_and_lookup(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    token = store.mint("cursor")
    assert token.startswith("teamshared_")

    ident = store.lookup(token)
    assert ident is not None
    assert ident.agent == "cursor"

    listing = store.list_agents()
    assert len(listing) == 1
    assert listing[0]["agent"] == "cursor"
    assert "..." in listing[0]["token_prefix"]


def test_token_store_revoke(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    token = store.mint("hermes")
    n = store.revoke(token[:12])
    assert n == 1
    assert store.lookup(token) is None


def test_token_store_revoke_requires_match(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    store.mint("hermes")
    assert store.revoke("nonexistent_prefix") == 0


def test_middleware_rejects_missing_header(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    app = _build_app(store)
    with TestClient(app) as client:
        resp = client.get("/mcp/whoami")
        assert resp.status_code == 401
        assert resp.json() == {"error": "missing_bearer_token"}


def test_middleware_rejects_unknown_token(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    store.mint("cursor")
    app = _build_app(store)
    with TestClient(app) as client:
        resp = client.get(
            "/mcp/whoami", headers={"Authorization": "Bearer bogus"}
        )
        assert resp.status_code == 401


def test_middleware_binds_identity(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    token = store.mint("cursor")
    app = _build_app(store)
    with TestClient(app) as client:
        resp = client.get(
            "/mcp/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"agent": "cursor"}


def test_health_is_anonymous(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    app = _build_app(store)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_auth_disabled_skips_check(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    app = _build_app(store, disabled=True)
    with TestClient(app) as client:
        resp = client.get("/mcp/whoami")
        assert resp.status_code == 200
        assert resp.json() == {"agent": "anonymous"}
