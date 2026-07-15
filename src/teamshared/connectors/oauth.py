"""OAuth 2.0 dance for the Gmail (Google) and Slack integrations.

Three steps, all async over httpx:

1. :func:`build_authorize_url` -- the URL the browser is redirected to.
2. :func:`exchange_code` -- swap the provider's auth code for an access + refresh
   token (returned as a :class:`TokenBundle`).
3. :func:`refresh_access_token` -- mint a fresh access token from a refresh
   token when the cached one expires.

Slack's newer apps use token rotation: each refresh returns a *new* refresh
token, so callers must persist the bundle returned here (not just the access
token). Google refresh tokens are long-lived (until revoked).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from teamshared.connectors.vault import TokenBundle
from teamshared.logging import get_logger

log = get_logger(__name__)

# Gmail scopes (read + send). ``gmail.readonly`` would block sending.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Slack scopes: read channels + post messages + list channels.
SLACK_SCOPES = [
    "channels:history",
    "channels:read",
    "chat:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
]


def _provider(kind: str) -> dict[str, str]:
    if kind == "gmail":
        return {
            "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
            "token": "https://oauth2.googleapis.com/token",
            "revoke": "https://oauth2.googleapis.com/revoke",
        }
    if kind == "slack":
        return {
            "authorize": "https://slack.com/oauth/v2/authorize",
            "token": "https://slack.com/api/oauth.v2.access",
            "revoke": "https://slack.com/api/auth.revoke",
        }
    raise ValueError(f"no OAuth provider configured for kind {kind!r}")


def build_authorize_url(
    kind: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Return the provider authorization URL the user is redirected to."""
    if kind == "gmail":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",  # ask for a refresh token
            "prompt": "consent",  # always re-consent so we always get a refresh token
            "state": state,
        }
        base = _provider(kind)["authorize"]
        return f"{base}?{urlencode(params)}"

    if kind == "slack":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(SLACK_SCOPES),
            "user_scope": ",".join(SLACK_SCOPES),
            "state": state,
        }
        base = _provider(kind)["authorize"]
        return f"{base}?{urlencode(params)}"

    raise ValueError(f"no OAuth provider configured for kind {kind!r}")


async def exchange_code(
    kind: str,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> TokenBundle:
    """Exchange an authorization code for an access (+ refresh) token bundle."""
    token_url = _provider(kind)["token"]
    if kind == "gmail":
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        expires_in = payload.get("expires_in")
        return TokenBundle(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope"),
            expires_at=_expires_at(expires_in),
        )

    if kind == "slack":
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"slack oauth.v2.access failed: {payload.get('error')}")
        authed = payload.get("authed_user", {})
        expires_in = authed.get("expires_in")
        return TokenBundle(
            access_token=authed.get("access_token") or payload.get("access_token", ""),
            refresh_token=authed.get("refresh_token"),
            token_type="Bearer",
            scope=authed.get("scope") or payload.get("scope"),
            expires_at=_expires_at(expires_in),
        )

    raise ValueError(f"no OAuth provider configured for kind {kind!r}")


async def refresh_access_token(
    kind: str,
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> TokenBundle:
    """Mint a fresh access token from a refresh token. Returns the new bundle.

    Slack token rotation: the response carries a *new* refresh token that
    supersedes the old one; callers must persist the returned bundle.
    """
    token_url = _provider(kind)["token"]
    if kind == "gmail":
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        expires_in = payload.get("expires_in")
        return TokenBundle(
            access_token=payload["access_token"],
            refresh_token=refresh_token,  # Google refresh tokens are long-lived
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope"),
            expires_at=_expires_at(expires_in),
        )

    if kind == "slack":
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"slack refresh failed: {payload.get('error')}")
        expires_in = payload.get("expires_in")
        return TokenBundle(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token") or refresh_token,
            token_type="Bearer",
            scope=payload.get("scope"),
            expires_at=_expires_at(expires_in),
        )

    raise ValueError(f"no OAuth provider configured for kind {kind!r}")


async def revoke_token(kind: str, *, token: str) -> bool:
    """Best-effort revoke at the provider. Returns True on success."""
    try:
        revoke_url = _provider(kind)["revoke"]
        async with httpx.AsyncClient(timeout=15.0) as client:
            if kind == "gmail":
                resp = await client.post(revoke_url, params={"token": token})
            else:
                resp = await client.post(revoke_url, data={"token": token})
            return resp.status_code == 200
    except Exception:  # noqa: BLE001 - revocation is best-effort
        log.warning("oauth_revoke_failed", kind=kind)
        return False


def _expires_at(expires_in: int | None) -> str | None:
    if expires_in is None:
        return None
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=int(expires_in))).isoformat()
