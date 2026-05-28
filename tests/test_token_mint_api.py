"""HTTP token mint + invite endpoints."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import TokenStore
from teamshared.config import Settings
from teamshared.invite import InviteStore
from teamshared.server.token_api import (
    MINT_SECRET_HEADER,
    handle_get_token_page,
    handle_root,
    handle_token_invite_create,
    handle_token_mint,
)


def _mint_app(settings: Settings, store: TokenStore, invites: InviteStore) -> Starlette:
    async def route(request):  # type: ignore[no-untyped-def]
        return await handle_token_mint(request, settings, store, invites)

    return Starlette(
        routes=[
            Route("/tokens/mint/{invite}/{agent}", route, methods=["POST"]),
            Route("/tokens/mint", route, methods=["POST"]),
        ]
    )


def _invite_app(settings: Settings, invites: InviteStore) -> Starlette:
    async def route(request):  # type: ignore[no-untyped-def]
        return await handle_token_invite_create(request, settings, invites)

    return Starlette(routes=[Route("/tokens/invites", route, methods=["POST"])])


def _get_token_app(settings: Settings, store: TokenStore, invites: InviteStore) -> Starlette:
    async def route(request):  # type: ignore[no-untyped-def]
        return await handle_get_token_page(request, settings, store, invites)

    return Starlette(
        routes=[
            Route("/get-token/{invite}/{agent}", route, methods=["GET"]),
            Route("/get-token", route, methods=["GET"]),
        ]
    )


def test_token_mint_disabled_when_both_paths_off(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret=None,
        self_service_tokens=False,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post("/tokens/mint", json={"agent": "cursor"})
        assert resp.status_code == 404
        assert resp.json() == {"error": "mint_disabled"}


def test_token_mint_requires_secret(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret="super-secret",
        self_service_tokens=False,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post("/tokens/mint", json={"agent": "cursor"})
        assert resp.status_code == 401
        assert resp.json() == {"error": "invalid_mint_secret"}


def test_token_mint_admin_success(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret="super-secret",
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post(
            "/tokens/mint",
            json={"agent": "cursor"},
            headers={MINT_SECRET_HEADER: "super-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "cursor"
        assert body["token"].startswith("teamshared_")
        assert store.lookup(body["token"]) is not None


def test_token_mint_rejects_invalid_agent(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret="super-secret",
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post(
            "/tokens/mint",
            json={"agent": "bad name"},
            headers={MINT_SECRET_HEADER: "super-secret"},
        )
        assert resp.status_code == 400


def test_token_mint_with_invite(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor", uses=1)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post(
            "/tokens/mint",
            json={"invite": record.code, "agent": "cursor-chad"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "cursor"
        assert body["token"].startswith("teamshared_")
        assert invites.get(record.code) is None


def test_token_mint_invite_requires_agent_when_unbound(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(uses=1)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post("/tokens/mint", json={"invite": record.code})
        assert resp.status_code == 400
        assert invites.get(record.code) is not None


def test_token_invite_create_requires_secret(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret="super-secret",
        invites_file=tmp_path / "invites.json",
    )
    invites = InviteStore(settings.invites_file)
    with TestClient(_invite_app(settings, invites)) as client:
        resp = client.post("/tokens/invites", json={"uses": 1})
        assert resp.status_code == 401


def test_token_invite_create_success(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret="super-secret",
        invites_file=tmp_path / "invites.json",
    )
    invites = InviteStore(settings.invites_file)
    with TestClient(_invite_app(settings, invites)) as client:
        resp = client.post(
            "/tokens/invites",
            json={"agent": "cursor", "uses": 2},
            headers={MINT_SECRET_HEADER: "super-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "cursor"
        assert body["uses_left"] == 2
        assert invites.get(body["invite"]) is not None


def test_token_mint_with_invite_path(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        mint_secret=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor", uses=1)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post(f"/tokens/mint/{record.code}/cursor-chad")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "cursor"
        assert body["token"].startswith("teamshared_")
        assert invites.get(record.code) is None


def test_get_token_page_redeems_invite_path(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor-web", uses=1)
    with TestClient(_get_token_app(settings, store, invites)) as client:
        resp = client.get(f"/get-token/{record.code}/cursor-web")
        assert resp.status_code == 200
        assert "teamshared_" in resp.text
        assert invites.get(record.code) is None


def _root_app(settings: Settings, store: TokenStore, invites: InviteStore) -> Starlette:
    async def route(request):  # type: ignore[no-untyped-def]
        return await handle_root(request, settings, store, invites)

    return Starlette(routes=[Route("/", route, methods=["GET"])])


def test_root_banner(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    with TestClient(_root_app(settings, store, invites)) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "teamshared-memory"
        assert "token_via_invite" in body


def test_root_redeems_invite_as_plain_text(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor-chad", uses=1)
    with TestClient(_root_app(settings, store, invites)) as client:
        resp = client.get("/", params={"invite": record.code, "agent": "cursor-chad"})
        assert resp.status_code == 200
        assert resp.text.startswith("teamshared_")
        assert resp.headers["content-type"].startswith("text/plain")
        assert invites.get(record.code) is None


def test_root_redeems_invite_as_json(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor", uses=1)
    with TestClient(_root_app(settings, store, invites)) as client:
        resp = client.get(
            "/",
            params={"invite": record.code, "agent": "cursor-chad"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "cursor"
        assert body["token"].startswith("teamshared_")


def test_get_token_page_shows_cursor_mcp_json(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor", uses=1)
    with TestClient(_get_token_app(settings, store, invites)) as client:
        resp = client.get(f"/get-token/{record.code}/cursor")
        assert resp.status_code == 200
        assert "Connect teamshared to Cursor" in resp.text
        assert "mcpServers" in resp.text
        assert "~/.cursor/mcp.json" in resp.text
        assert "plugins/local/teamshared-memory" in resp.text
        assert "Settings → Plugins" in resp.text
        assert "Memory rule" in resp.text
        assert "teamshared-memory.mdc" in resp.text
        assert "teamshared Memory Protocol" in resp.text
        assert "~/.cursor/rules/teamshared-memory.mdc" in resp.text
        assert 'id="about-teamshared"' in resp.text
        assert "Multi-pillar agent memory" in resp.text
        assert "memory_recall" in resp.text


def test_get_token_form_shows_readme(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    with TestClient(_get_token_app(settings, store, invites)) as client:
        resp = client.get("/get-token")
        assert resp.status_code == 200
        assert 'id="about-teamshared"' in resp.text
        assert "Learn what teamshared does" in resp.text
        assert "MCP tools" in resp.text


def test_invite_normalizes_cursor_chad_to_cursor(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor", uses=1)
    with TestClient(_mint_app(settings, store, invites)) as client:
        resp = client.post(f"/tokens/mint/{record.code}/cursor-chad")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == "cursor"
        assert store.lookup(body["token"]).agent == "cursor"  # type: ignore[union-attr]


def test_get_token_page_redeems_invite(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        self_service_tokens=True,
        tokens_file=tmp_path / "tokens.json",
        invites_file=tmp_path / "invites.json",
    )
    store = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent="cursor-web", uses=1)
    with TestClient(_get_token_app(settings, store, invites)) as client:
        resp = client.get(
            "/get-token",
            params={"invite": record.code, "agent": "cursor-web"},
        )
        assert resp.status_code == 200
        assert "teamshared_" in resp.text
        assert invites.get(record.code) is None
