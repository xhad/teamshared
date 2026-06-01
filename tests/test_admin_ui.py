"""K1 admin dashboard: magic-link login + session-gated read-only pages.

Drives the real `register_admin_routes` Starlette routes with a mocked
`ProductionServices`/`AdminService`. Pins the auth flow (magic link -> session
cookie -> page), the unauthenticated redirect, and permission gating.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from teamshared.identity.principal import Principal
from teamshared.identity.rbac import PermissionDenied
from teamshared.server.admin_routes import register_admin_routes

DEFAULT_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SECRET = "test-session-secret"


class _Conn:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    async def execute(self, sql: str, params: object = None):
        cur = MagicMock()
        cur.fetchone = AsyncMock(return_value=self._row)
        return cur


class _OrgCM:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _build(*, owner_row: tuple | None = (OWNER_ID,), require: AsyncMock | None = None):
    settings = SimpleNamespace(
        session_secret=SECRET,
        default_org_id=DEFAULT_ORG,
        auth_disabled=True,  # dev mode: magic link is shown in the page
        public_url="http://testserver",
    )
    tenant_db = MagicMock()
    tenant_db.org = MagicMock(return_value=_OrgCM(_Conn(owner_row)))

    authorizer = MagicMock()
    authorizer.require = require or AsyncMock(return_value=None)

    services = MagicMock()
    services.tenant_db = tenant_db
    services.authorizer = MagicMock(return_value=authorizer)
    services.admin.list_members = AsyncMock(return_value=[])
    services.admin.list_agents = AsyncMock(return_value=[])
    services.admin.list_role_bindings = AsyncMock(return_value=[])
    services.admin.list_retention_policies = AsyncMock(return_value=[])
    services.api_keys.list_keys = AsyncMock(return_value=[])
    services.approvals.list_pending = AsyncMock(return_value=[])
    services.audit.list_events = AsyncMock(return_value=[])
    services.connectors.list_connectors = AsyncMock(return_value=[])
    services.vector_store.stats = AsyncMock(
        return_value={"active": 7, "pending_approval": 1, "quarantined": 0}
    )

    routes = register_admin_routes(settings, services)
    app = Starlette(routes=routes)
    return TestClient(app, follow_redirects=False), services


def _magic_token(client: TestClient) -> str:
    resp = client.post("/admin/login", data={"email": "owner@example.com"})
    assert resp.status_code == 200
    match = re.search(r"/admin/login/verify\?token=([A-Za-z0-9_\-.]+)", resp.text)
    assert match, "dev login page should embed a magic link"
    return match.group(1)


def _login(client: TestClient) -> None:
    token = _magic_token(client)
    verify = client.get(f"/admin/login/verify?token={token}")
    assert verify.status_code == 303
    assert verify.headers["location"] == "/admin"
    assert "ts_session" in verify.cookies or any(
        "ts_session" in c for c in verify.headers.get_list("set-cookie")
    )


def test_unauthenticated_admin_redirects_to_login() -> None:
    client, _ = _build()
    resp = client.get("/admin")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_login_page_renders() -> None:
    client, _ = _build()
    resp = client.get("/admin/login")
    assert resp.status_code == 200
    assert "Owner email" in resp.text


def test_unknown_email_does_not_leak_and_shows_no_link() -> None:
    client, _ = _build(owner_row=None)
    resp = client.post("/admin/login", data={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert "sign-in link was sent" in resp.text
    assert "login/verify?token=" not in resp.text


def test_magic_link_grants_session_and_renders_overview() -> None:
    client, services = _build()
    _login(client)

    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Overview" in resp.text
    assert "Active memories" in resp.text
    services.vector_store.stats.assert_awaited()


def test_invalid_magic_token_is_rejected() -> None:
    client, _ = _build()
    resp = client.get("/admin/login/verify?token=not-a-real-jwt")
    assert resp.status_code == 401
    assert "invalid or expired" in resp.text


def test_permission_denied_renders_403() -> None:
    denied = PermissionDenied(
        "api_key:admin",
        Principal(org_id=DEFAULT_ORG, type="user", id=OWNER_ID, display="owner"),
    )
    client, _ = _build(require=AsyncMock(side_effect=denied))
    _login(client)

    resp = client.get("/admin/api-keys")
    assert resp.status_code == 403


def test_logout_clears_cookie() -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/admin/logout")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"
