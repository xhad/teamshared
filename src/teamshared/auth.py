"""Per-agent bearer-token auth.

Tokens are stored in a JSON file at :attr:`Settings.tokens_file`. Each entry
maps a token to an agent identity::

    {
      "<token>": {"agent": "cursor", "created_at": "..."},
      "<token>": {"agent": "hermes", "created_at": "..."}
    }

The ``agent`` field flows through to memory writes so we can attribute facts
and scope reads. The middleware also exposes the resolved identity via the
``request.state.agent`` attribute and the ``teamshared.current_agent`` contextvar so
tool implementations don't have to dig through the request.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.metrics import METRICS
from teamshared.server.route_policy import outer_middleware_skips_bearer

log = get_logger(__name__)


@dataclass(frozen=True)
class AgentIdentity:
    """Resolved identity for a request after bearer validation."""

    agent: str
    state_id: str


def _derive_state_id(token: str, entry: dict[str, Any]) -> str:
    """Return a unique per-token scope id for client state storage."""
    stored = entry.get("state_id")
    if stored:
        return str(stored)
    # Legacy tokens minted before state_id existed: stable hash of the secret.
    return hashlib.sha256(token.encode()).hexdigest()[:32]


_current_agent: contextvars.ContextVar[AgentIdentity | None] = contextvars.ContextVar(
    "teamshared_current_agent", default=None
)
_current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "teamshared_current_principal", default=None
)


def current_agent() -> AgentIdentity | None:
    """Return the agent identity bound to the current task, if any."""
    return _current_agent.get()


def require_current_agent() -> AgentIdentity:
    """Same as :func:`current_agent` but raises if missing."""
    agent = _current_agent.get()
    if agent is None:
        raise RuntimeError("No agent identity bound to this request")
    return agent


def current_principal() -> Principal | None:
    """Return the org-scoped Principal bound to the current task, if any."""
    return _current_principal.get()


def require_current_principal() -> Principal:
    """Same as :func:`current_principal` but raises if missing."""
    principal = _current_principal.get()
    if principal is None:
        raise RuntimeError("No principal bound to this request")
    return principal


class TokenStore:
    """Tiny JSON-file-backed token registry.

    Reads are O(n) over tokens; n is expected to be tiny (one token per agent
    per device). All mutations rewrite the file atomically.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open() as fh:
            data: dict[str, dict[str, Any]] = json.load(fh)
        return data

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        tmp.replace(self.path)

    def lookup(self, token: str) -> AgentIdentity | None:
        entry = self._load().get(token)
        if entry is None:
            return None
        return AgentIdentity(agent=entry["agent"], state_id=_derive_state_id(token, entry))

    def mint(self, agent: str) -> str:
        """Generate a new token for ``agent`` and persist it. Returns the raw token."""
        token = "teamshared_" + secrets.token_urlsafe(32)
        data = self._load()
        data[token] = {
            "agent": agent,
            "created_at": datetime.now(UTC).isoformat(),
            "state_id": secrets.token_hex(16),
        }
        self._save(data)
        return token

    def revoke(self, token_prefix: str) -> int:
        """Remove all tokens starting with ``token_prefix``. Returns count removed."""
        data = self._load()
        to_remove = [tok for tok in data if tok.startswith(token_prefix)]
        for tok in to_remove:
            del data[tok]
        self._save(data)
        return len(to_remove)

    def list_agents(self) -> list[dict[str, str]]:
        """Return ``[{agent, token_prefix, created_at}, ...]`` without exposing raw tokens."""
        return [
            {
                "agent": entry["agent"],
                "token_prefix": tok[:12] + "...",
                "created_at": entry.get("created_at", ""),
            }
            for tok, entry in sorted(self._load().items(), key=lambda kv: kv[1]["agent"])
        ]

    def legacy_entries(self) -> list[tuple[str, str]]:
        """Return ``(raw_token, agent)`` for every legacy file-backed token."""
        return [
            (token, str(entry["agent"]))
            for token, entry in self._load().items()
        ]


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate ``Authorization: Bearer <token>`` against a :class:`TokenStore`.

    - ``/health``, ``/``, ``/favicon.ico``, and token self-service paths are anonymous.
    - If ``auth_disabled`` is True, a synthetic ``anonymous`` identity is bound
      (useful for local development / tests).
    """

    def __init__(
        self,
        app: ASGIApp,
        store: TokenStore,
        *,
        auth_disabled: bool = False,
        resolver: PrincipalResolver | None = None,
    ) -> None:
        super().__init__(app)
        self.store = store
        self.auth_disabled = auth_disabled
        self.resolver = resolver

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if outer_middleware_skips_bearer(path):
            return await call_next(request)

        identity: AgentIdentity | None
        token: str | None = None
        if self.auth_disabled:
            identity = AgentIdentity(agent="anonymous", state_id="disabled")
        else:
            header = request.headers.get("authorization", "")
            if not header.lower().startswith("bearer "):
                METRICS.auth_rejected.inc(reason="missing_bearer")
                return JSONResponse(
                    {"error": "missing_bearer_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = header[len("bearer ") :].strip()
            identity = self.store.lookup(token)

        principal = await self._resolve_principal(token, identity)
        if not self.auth_disabled and identity is None and principal is None:
            METRICS.auth_rejected.inc(reason="invalid_token")
            log.warning("auth_rejected", token_prefix=(token or "")[:8])
            return JSONResponse({"error": "invalid_token"}, status_code=401)

        # A tsk_/session principal carries no legacy AgentIdentity; synthesize
        # one so working-memory capture and bearer-scoped client state still key
        # off a stable string.
        if identity is None and principal is not None:
            identity = AgentIdentity(
                agent=principal.display or principal.attribution,
                state_id=f"p:{principal.type}:{principal.id}",
            )

        request.state.agent = identity
        request.state.principal = principal
        agent_token = _current_agent.set(identity)
        principal_token = _current_principal.set(principal)
        try:
            return await call_next(request)
        finally:
            _current_agent.reset(agent_token)
            _current_principal.reset(principal_token)

    async def _resolve_principal(
        self, token: str | None, identity: AgentIdentity | None
    ) -> Principal | None:
        if self.resolver is None:
            return None
        try:
            if self.auth_disabled:
                return await self.resolver.anonymous()
            if token is None:
                return None
            return await self.resolver.resolve(
                token, legacy_agent=identity.agent if identity else None
            )
        except Exception as exc:  # resolution must not 500 the request
            log.warning("principal_resolution_failed", error=str(exc))
            return None
