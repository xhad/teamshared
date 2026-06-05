"""CSRF protection for browser POST forms under ``/app/*``.

Tokens are HMAC-SHA256 derivations of the signed-in user's org + user id (stable
for the lifetime of a console session). A matching ``ts_csrf`` cookie is set on
GET ``/app/*`` responses (double-submit) so POST bodies stay aligned with the
browser's session even when a tab was opened before an org switch.

Legacy tokens derived from the raw ``ts_session`` JWT string are still accepted.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from teamshared.identity.sessions import verify_session

_CSRF_COOKIE = "ts_csrf"
_SESSION_COOKIE = "ts_session"


def cookie_secure(request: Request, *, auth_disabled: bool) -> bool:
    """Whether Set-Cookie should include ``Secure`` (honours reverse proxies)."""
    if auth_disabled:
        return False
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded:
        return forwarded == "https"
    return request.url.scheme == "https"


def csrf_token_for_principal(org_id: UUID | str, user_id: UUID | str, secret: str) -> str:
    """CSRF token bound to org + user (preferred; survives JWT re-issue)."""
    material = f"teamshared-console-csrf:{org_id}:{user_id}"
    digest = hmac.new(
        secret.encode("utf-8"),
        material.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def csrf_token_for_session(session_token: str, secret: str) -> str:
    """Legacy CSRF token bound to the raw session JWT string."""
    digest = hmac.new(
        secret.encode("utf-8"),
        b"teamshared-console-csrf:" + session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def csrf_token_for_request(request: Request, secret: str) -> str | None:
    """Return the CSRF token for the current console session, if authenticated."""
    session = request.cookies.get(_SESSION_COOKIE)
    if not session or not secret:
        return None
    principal = verify_session(session, secret=secret)
    if principal is None:
        return None
    return csrf_token_for_principal(principal.org_id, principal.id, secret)


def csrf_failure_reason(
    session_token: str | None,
    secret: str,
    submitted: str | None,
    csrf_cookie: str | None,
) -> Literal["missing_session", "missing_secret", "missing_token", "mismatch"]:
    if not session_token:
        return "missing_session"
    if not secret:
        return "missing_secret"
    if not submitted:
        return "missing_token"
    return "mismatch"


def _token_matches(
    token: str,
    *,
    secret: str,
    session_token: str | None,
    org_id: UUID | str | None,
    user_id: UUID | str | None,
) -> bool:
    if org_id is not None and user_id is not None:
        expected = csrf_token_for_principal(org_id, user_id, secret)
        if hmac.compare_digest(expected, token):
            return True

    if session_token:
        principal = verify_session(session_token, secret=secret)
        if principal is not None:
            expected = csrf_token_for_principal(principal.org_id, principal.id, secret)
            if hmac.compare_digest(expected, token):
                return True
        expected = csrf_token_for_session(session_token, secret)
        if hmac.compare_digest(expected, token):
            return True

    return False


def verify_console_csrf(
    session_token: str | None,
    secret: str,
    submitted: str | None,
    *,
    csrf_cookie: str | None = None,
    org_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
) -> bool:
    """Validate a form ``csrf_token`` against session, principal, or cookie."""
    if not secret:
        return False

    candidates: list[str] = []
    if submitted and submitted.strip():
        candidates.append(submitted.strip())
    if csrf_cookie and csrf_cookie.strip():
        cookie_val = csrf_cookie.strip()
        if cookie_val not in candidates:
            candidates.append(cookie_val)

    if not candidates:
        return False

    for token in candidates:
        if _token_matches(
            token,
            secret=secret,
            session_token=session_token,
            org_id=org_id,
            user_id=user_id,
        ):
            return True

    return False


class ConsoleCsrfCookieMiddleware(BaseHTTPMiddleware):
    """Refresh ``ts_csrf`` on authenticated console GET responses."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_secret: str | None,
        auth_disabled: bool,
        session_ttl: int = 3600,
    ) -> None:
        super().__init__(app)
        self._secret = session_secret
        self._auth_disabled = auth_disabled
        self._session_ttl = session_ttl

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        if request.method != "GET" or not request.url.path.startswith("/app"):
            return response
        if not self._secret:
            return response
        token = csrf_token_for_request(request, self._secret)
        if not token:
            return response
        response.set_cookie(
            _CSRF_COOKIE,
            token,
            max_age=self._session_ttl,
            httponly=False,
            samesite="lax",
            secure=cookie_secure(request, auth_disabled=self._auth_disabled),
            path="/",
        )
        return response
