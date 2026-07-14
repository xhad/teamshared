"""Short-lived JWT sessions for human (console) auth.

API keys cover programmatic/agent access; humans logging into the console
prove ownership of their member email via a one-time passcode (see
``WorkingMemory.set_login_otp`` / ``verify_login_otp``) and then receive a
signed ``typ=user`` JWT carrying their org + user id. OIDC/SAML federation
slots in above this by minting the same session token after an external
assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from teamshared.identity.principal import Principal

_ALG = "HS256"


def issue_session(
    *,
    secret: str,
    org_id: UUID,
    user_id: UUID,
    email: str | None = None,
    account_id: UUID | None = None,
    ttl_seconds: int = 3600,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "org": str(org_id),
        "typ": "user",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    if email:
        # The global account email: stable across orgs, drives the org switcher.
        payload["email"] = email
    if account_id is not None:
        payload["aid"] = str(account_id)
    return jwt.encode(payload, secret, algorithm=_ALG)


def verify_session(token: str, *, secret: str) -> Principal | None:
    return _verify(token, secret=secret, expected_typ="user")


def _verify(token: str, *, secret: str, expected_typ: str) -> Principal | None:
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALG])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != expected_typ:
        return None
    try:
        account_id = None
        raw_aid = payload.get("aid")
        if raw_aid:
            account_id = UUID(str(raw_aid))
        return Principal(
            org_id=UUID(payload["org"]),
            type="user",
            id=UUID(payload["sub"]),
            display=payload.get("email"),
            account_id=account_id,
        )
    except (KeyError, ValueError):
        return None
