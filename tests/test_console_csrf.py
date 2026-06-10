"""Console CSRF (Stage 5.1 + hardening)."""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock

import jwt
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.identity.sessions import issue_session
from teamshared.server.console_csrf import (
    ConsoleCsrfCookieMiddleware,
    csrf_token_for_principal,
    csrf_token_for_session,
    verify_console_csrf,
)
from tests.test_console import DEFAULT_ORG, OWNER_ID, SECRET, _app_post, _build, _login

ORG = DEFAULT_ORG
USER = OWNER_ID


def test_csrf_token_roundtrip_session() -> None:
    session = "fake-session-jwt"
    token = csrf_token_for_session(session, SECRET)
    assert verify_console_csrf(session, SECRET, token)
    assert not verify_console_csrf(session, SECRET, "wrong")
    assert not verify_console_csrf(None, SECRET, token)


def test_csrf_token_roundtrip_principal() -> None:
    token = csrf_token_for_principal(ORG, USER, SECRET)
    assert verify_console_csrf(
        None, SECRET, token, org_id=ORG, user_id=USER
    )
    assert verify_console_csrf("any-session", SECRET, token, org_id=ORG, user_id=USER)
    assert not verify_console_csrf(None, SECRET, "wrong", org_id=ORG, user_id=USER)


def test_csrf_double_submit_cookie() -> None:
    token = csrf_token_for_principal(ORG, USER, SECRET)
    assert verify_console_csrf(
        None, SECRET, None, csrf_cookie=token, org_id=ORG, user_id=USER
    )
    assert not verify_console_csrf(
        None, SECRET, None, csrf_cookie="other", org_id=ORG, user_id=USER
    )


def test_post_without_csrf_rejected() -> None:
    client, _ = _build()
    _login(client)
    client.cookies.pop("ts_csrf", None)
    resp = client.post("/app/agents/add", data={"name": "evil-bot"})
    assert resp.status_code == 403
    assert "CSRF" in resp.text or "blocked" in resp.text.lower()


def test_post_with_csrf_from_page_succeeds() -> None:
    client, _ = _build()
    _login(client)
    resp = _app_post(client, "/app/agents/add", {"name": "csrf-test-agent"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/agents"


def test_people_form_renders_csrf_hidden_field() -> None:
    """Imported Jinja macros must use ``with context`` to see ``csrf_token``."""
    client, _ = _build()
    _login(client)
    resp = client.get("/app/people")
    assert resp.status_code == 200
    assert 'name="csrf_token"' in resp.text
    assert 'value="' in resp.text


def test_people_add_accepts_csrf_cookie_without_form_field() -> None:
    """Belt-and-suspenders: cookie-only verify when the hidden field is absent."""
    client, services = _build()
    services.admin.add_member = AsyncMock(
        return_value={"user_id": "new", "email": "x@y.z", "role": "member"}
    )
    _login(client)
    csrf = client.cookies.get("ts_csrf")
    assert csrf
    resp = client.post(
        "/app/people/add",
        data={"email": "new@team.io", "role": "member"},
        cookies={"ts_session": client.cookies["ts_session"], "ts_csrf": csrf},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/people"


def _rolling_app(ttl: int = 2_592_000) -> TestClient:
    async def app_home(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/app", app_home, methods=["GET"])])
    app.add_middleware(
        ConsoleCsrfCookieMiddleware,
        session_secret=SECRET,
        auth_disabled=True,
        session_ttl=ttl,
    )
    return TestClient(app, follow_redirects=False)


def test_rolling_session_reissues_cookie_with_long_ttl() -> None:
    client = _rolling_app(ttl=2_592_000)
    token = issue_session(secret=SECRET, org_id=ORG, user_id=USER, email="a@b.c", ttl_seconds=60)
    resp = client.get("/app", cookies={"ts_session": token})
    assert resp.status_code == 200
    set_cookies = "\n".join(resp.headers.get_list("set-cookie"))
    assert "ts_session=" in set_cookies
    assert "ts_csrf=" in set_cookies
    assert "Max-Age=2592000" in set_cookies
    # The refreshed JWT carries a later expiry than the short-lived input token.
    new_token = client.cookies.get("ts_session")
    old = jwt.decode(token, SECRET, algorithms=["HS256"])
    new = jwt.decode(new_token, SECRET, algorithms=["HS256"])
    assert new["exp"] > old["exp"]


def test_rolling_session_skips_when_unauthenticated() -> None:
    client = _rolling_app()
    resp = client.get("/app")  # no session cookie
    assert resp.status_code == 200
    assert "ts_session=" not in "\n".join(resp.headers.get_list("set-cookie"))


def test_rolling_session_ignores_invalid_cookie() -> None:
    client = _rolling_app()
    resp = client.get("/app", cookies={"ts_session": "not-a-jwt"})
    assert resp.status_code == 200
    assert "ts_session=" not in "\n".join(resp.headers.get_list("set-cookie"))


def test_login_sets_ts_csrf_cookie() -> None:
    client, _ = _build()
    _login(client)
    assert client.cookies.get("ts_csrf")


def test_org_switch_refreshes_csrf_cookie() -> None:
    client, services = _build()
    other_org = uuid.uuid4()
    other_user = uuid.uuid4()
    services.accounts.list_orgs = AsyncMock(
        return_value=[
            {"org_id": DEFAULT_ORG, "user_id": OWNER_ID, "name": "A", "slug": "a", "role": "owner"},
            {"org_id": other_org, "user_id": other_user, "name": "B", "slug": "b", "role": "owner"},
        ]
    )
    _login(client)
    before = client.cookies.get("ts_csrf")
    page = client.get("/app/agents")
    assert page.status_code == 200
    match = re.search(
        r'<meta name="csrf-token" content="([^"]+)"'
        r'|name="csrf_token" value="([^"]+)"',
        page.text,
    )
    assert match
    csrf = match.group(1) or match.group(2)
    resp = client.post(
        "/app/orgs/switch",
        data={"org_id": str(other_org), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    after = client.cookies.get("ts_csrf")
    assert after and after != before
