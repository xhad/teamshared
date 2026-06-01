"""Short-lived JWT sessions for human (dashboard) auth.

API keys cover programmatic/agent access; humans logging into the dashboard
get a signed JWT carrying their org + user id. OIDC/SAML federation slots in
above this by minting the same session token after an external assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from teamshared.identity.principal import Principal

_ALG = "HS256"


def issue_session(
    *, secret: str, org_id: UUID, user_id: UUID, ttl_seconds: int = 3600
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "typ": "user",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALG)


def verify_session(token: str, *, secret: str) -> Principal | None:
    return _verify(token, secret=secret, expected_typ="user")


def issue_magic(
    *, secret: str, org_id: UUID, user_id: UUID, ttl_seconds: int = 900
) -> str:
    """Issue a short-lived single-purpose magic-link token (``typ=magic``).

    Exchanged at the verify endpoint for a real ``typ=user`` session. Kept
    short (15 min default) since the link travels over email.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "typ": "magic",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALG)


def verify_magic(token: str, *, secret: str) -> Principal | None:
    return _verify(token, secret=secret, expected_typ="magic")


def _verify(token: str, *, secret: str, expected_typ: str) -> Principal | None:
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALG])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != expected_typ:
        return None
    try:
        return Principal(
            org_id=UUID(payload["org"]),
            type="user",
            id=UUID(payload["sub"]),
        )
    except (KeyError, ValueError):
        return None
