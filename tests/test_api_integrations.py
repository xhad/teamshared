"""REST API integration routes (OAuth start/callback, list/disconnect/sync).

Unit-level: mounts ``integration_routes`` with a mocked
``ProductionServices`` and a fake session cookie, mirroring test_api.py.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from teamshared.connectors.vault import TokenBundle
from teamshared.identity.principal import Principal
from teamshared.server.api.integrations import integration_routes

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SECRET = "test-session-secret"


def _principal() -> Principal:
    return Principal(
        org_id=ORG, type="user", id=USER_ID, account_id=ACCOUNT,
        display="owner@example.com",
    )


def _services(*, configured: bool = True) -> MagicMock:
    services = MagicMock()
    services.settings = SimpleNamespace(
        session_secret=SECRET,
        gmail_client_id="gmail-cid" if configured else None,
        gmail_client_secret="gmail-sec" if configured else None,
        gmail_redirect_uri="https://app/v1/integrations/oauth/callback" if configured else None,
        slack_client_id="slack-cid" if configured else None,
        slack_client_secret="slack-sec" if configured else None,
        slack_redirect_uri="https://app/v1/integrations/oauth/callback" if configured else None,
    )
    services.tenant_db = MagicMock()
    services.authorizer = MagicMock(return_value=SimpleNamespace(
        require=AsyncMock(), has=AsyncMock(return_value=True),
    ))
    services.working = MagicMock()
    services.working.set_oauth_state = AsyncMock(return_value=None)
    services.working.pop_oauth_state = AsyncMock(return_value=None)
    services.connectors = MagicMock()
    services.connectors.list_connectors = AsyncMock(return_value=[])
    services.connectors.create_oauth_connection = AsyncMock(return_value=uuid.uuid4())
    services.connectors.get_connector = AsyncMock(return_value=None)
    services.connectors.get_token_bundle = AsyncMock(return_value=None)
    services.connectors.delete = AsyncMock(return_value=True)
    services.connectors.sync = AsyncMock(return_value=SimpleNamespace(
        connector_id=uuid.uuid4(), fetched=0, imported=0, next_cursor=None,
    ))
    return services


def _app(services: MagicMock, *, principal: Principal | None = _principal()) -> Starlette:
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.routing import Mount

    class _InjectPrincipal(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.principal = principal
            return await call_next(request)

    # Mount integration routes at /v1 like production so the route paths
    # (defined without the /v1 prefix inside the sub-app) resolve correctly.
    sub = Starlette(
        routes=integration_routes(services),
        middleware=([Middleware(_InjectPrincipal)] if principal is not None else []),
    )
    return Starlette(routes=[Mount("/v1", app=sub)])


def _session_cookie() -> str:
    # A non-empty cookie; verify_session is patched per-test.
    return "fake-session-token"


# --- oauth start ------------------------------------------------------------


def test_oauth_start_without_session_redirects_to_login() -> None:
    services = _services()
    app = _app(services, principal=None)
    with TestClient(app, follow_redirects=False) as client:
        resp = client.get("/v1/integrations/oauth/start?kind=gmail")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_oauth_start_bad_kind_returns_400() -> None:
    services = _services()
    app = _app(services)
    with patch(
        "teamshared.server.api.integrations.verify_session",
        return_value=_principal(),
    ), TestClient(app, follow_redirects=False) as client:
        resp = client.get(
            "/v1/integrations/oauth/start?kind=dropbox",
            cookies={"ts_session": _session_cookie()},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_oauth_start_unconfigured_returns_503() -> None:
    services = _services(configured=False)
    app = _app(services)
    with patch(
        "teamshared.server.api.integrations.verify_session",
        return_value=_principal(),
    ), TestClient(app, follow_redirects=False) as client:
        resp = client.get(
            "/v1/integrations/oauth/start?kind=gmail",
            cookies={"ts_session": _session_cookie()},
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not_configured"


def test_oauth_start_redirects_to_provider() -> None:
    services = _services()
    app = _app(services)
    with patch(
        "teamshared.server.api.integrations.verify_session",
        return_value=_principal(),
    ), TestClient(app, follow_redirects=False) as client:
        resp = client.get(
            "/v1/integrations/oauth/start?kind=gmail",
            cookies={"ts_session": _session_cookie()},
        )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    services.working.set_oauth_state.assert_awaited_once()
    state_arg = services.working.set_oauth_state.await_args.args[0]
    payload = services.working.set_oauth_state.await_args.args[1]
    assert payload["kind"] == "gmail"
    assert payload["account_id"] == str(ACCOUNT)
    assert payload["org_id"] == str(ORG)


def test_oauth_start_returns_json_for_api_caller() -> None:
    services = _services()
    app = _app(services)
    with patch(
        "teamshared.server.api.integrations.verify_session",
        return_value=_principal(),
    ), TestClient(app, follow_redirects=False) as client:
        resp = client.get(
            "/v1/integrations/oauth/start?kind=slack",
            headers={"accept": "application/json"},
            cookies={"ts_session": _session_cookie()},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "slack"
    assert body["authorize_url"].startswith("https://slack.com/oauth/v2/authorize?")


# --- oauth callback ---------------------------------------------------------


def test_oauth_callback_missing_params_redirects_error() -> None:
    services = _services()
    app = _app(services)
    with TestClient(app, follow_redirects=False) as client:
        resp = client.get("/v1/integrations/oauth/callback")
    assert resp.status_code == 303
    assert "reason=missing_params" in resp.headers["location"]


def test_oauth_callback_invalid_state_redirects_error() -> None:
    services = _services()
    services.working.pop_oauth_state = AsyncMock(return_value=None)
    app = _app(services)
    with TestClient(app, follow_redirects=False) as client:
        resp = client.get("/v1/integrations/oauth/callback?code=c&state=s")
    assert resp.status_code == 303
    assert "reason=invalid_state" in resp.headers["location"]


def test_oauth_callback_success_creates_connection() -> None:
    services = _services()
    services.working.pop_oauth_state = AsyncMock(
        return_value={"kind": "gmail", "org_id": str(ORG), "account_id": str(ACCOUNT),
                      "redirect_uri": "https://app/v1/integrations/oauth/callback"}
    )
    bundle = TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=None)
    app = _app(services)
    with patch(
        "teamshared.server.api.integrations.verify_session",
        return_value=_principal(),
    ), patch(
        "teamshared.connectors.oauth.exchange_code", new=AsyncMock(return_value=bundle),
    ), TestClient(app, follow_redirects=False) as client:
        resp = client.get(
            "/v1/integrations/oauth/callback?code=the-code&state=st123",
            cookies={"ts_session": _session_cookie()},
        )
    assert resp.status_code == 303
    assert "status=connected" in resp.headers["location"]
    assert "kind=gmail" in resp.headers["location"]
    services.connectors.create_oauth_connection.assert_awaited_once()
    call = services.connectors.create_oauth_connection.await_args
    assert call.kwargs["kind"] == "gmail"
    assert call.kwargs["bundle"] is bundle


def test_oauth_callback_no_session_redirects_error() -> None:
    services = _services()
    services.working.pop_oauth_state = AsyncMock(
        return_value={"kind": "gmail", "org_id": str(ORG), "account_id": str(ACCOUNT),
                      "redirect_uri": "https://app/v1/integrations/oauth/callback"}
    )
    bundle = TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=None)
    app = _app(services, principal=None)
    with patch(
        "teamshared.server.api.integrations.verify_session",
        return_value=None,
    ), patch(
        "teamshared.connectors.oauth.exchange_code", new=AsyncMock(return_value=bundle),
    ), TestClient(app, follow_redirects=False) as client:
        resp = client.get("/v1/integrations/oauth/callback?code=c&state=s")
    assert resp.status_code == 303
    assert "reason=no_session" in resp.headers["location"]


# --- list / disconnect / sync ----------------------------------------------


def test_list_integrations_returns_items() -> None:
    services = _services()
    services.connectors.list_connectors = AsyncMock(
        return_value=[{"id": "c-1", "kind": "gmail", "status": "connected"}]
    )
    app = _app(services)
    with TestClient(app) as client:
        resp = client.get("/v1/integrations")
    assert resp.status_code == 200
    assert resp.json()["integrations"][0]["kind"] == "gmail"


def test_disconnect_integration_revokes_and_deletes() -> None:
    services = _services()
    cid = uuid.uuid4()
    services.connectors.get_connector = AsyncMock(
        return_value={"id": str(cid), "kind": "gmail", "config": {}}
    )
    services.connectors.get_token_bundle = AsyncMock(
        return_value=TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=None)
    )
    app = _app(services)
    with patch(
        "teamshared.connectors.oauth.revoke_token", new=AsyncMock(return_value=None),
    ), TestClient(app) as client:
        resp = client.delete(f"/v1/integrations/{cid}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    services.connectors.delete.assert_awaited_once()


def test_sync_integration_returns_report() -> None:
    services = _services()
    cid = uuid.uuid4()
    services.connectors.sync = AsyncMock(return_value=SimpleNamespace(
        connector_id=cid, fetched=3, imported=3, next_cursor="page2",
    ))
    app = _app(services)
    with TestClient(app) as client:
        resp = client.post(f"/v1/integrations/{cid}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fetched"] == 3
    assert body["imported"] == 3
    assert body["next_cursor"] == "page2"

