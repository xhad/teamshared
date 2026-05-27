"""Per-agent bearer-token auth.

Tokens are stored in a JSON file at :attr:`Settings.tokens_file`. Each entry
maps a token to an agent identity::

    {
      "<token>": {"agent": "cursor", "created_at": "..."},
      "<token>": {"agent": "hermes", "created_at": "..."}
    }

The ``agent`` field flows through to memory writes so we can attribute facts
and scope reads. The middleware also exposes the resolved identity via the
``request.state.agent`` attribute and the ``sptx.current_agent`` contextvar so
tool implementations don't have to dig through the request.
"""

from __future__ import annotations

import contextvars
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

from sptx.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class AgentIdentity:
    """Resolved identity for a request after bearer validation."""

    agent: str
    token_prefix: str


_current_agent: contextvars.ContextVar[AgentIdentity | None] = contextvars.ContextVar(
    "sptx_current_agent", default=None
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
        return AgentIdentity(agent=entry["agent"], token_prefix=token[:8])

    def mint(self, agent: str) -> str:
        """Generate a new token for ``agent`` and persist it. Returns the raw token."""
        token = "sptx_" + secrets.token_urlsafe(32)
        data = self._load()
        data[token] = {
            "agent": agent,
            "created_at": datetime.now(UTC).isoformat(),
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


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate ``Authorization: Bearer <token>`` against a :class:`TokenStore`.

    Two escape hatches:
    - ``/health`` and ``/`` are always anonymous.
    - If ``auth_disabled`` is True, a synthetic ``anonymous`` identity is bound
      (useful for local development / tests).
    """

    def __init__(
        self,
        app: ASGIApp,
        store: TokenStore,
        *,
        auth_disabled: bool = False,
    ) -> None:
        super().__init__(app)
        self.store = store
        self.auth_disabled = auth_disabled

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in {"/health", "/"}:
            return await call_next(request)

        if self.auth_disabled:
            identity = AgentIdentity(agent="anonymous", token_prefix="disabled")
        else:
            header = request.headers.get("authorization", "")
            if not header.lower().startswith("bearer "):
                return JSONResponse(
                    {"error": "missing_bearer_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = header[len("bearer ") :].strip()
            identity = self.store.lookup(token)
            if identity is None:
                log.warning("auth_rejected", token_prefix=token[:8])
                return JSONResponse({"error": "invalid_token"}, status_code=401)

        request.state.agent = identity
        token = _current_agent.set(identity)
        try:
            return await call_next(request)
        finally:
            _current_agent.reset(token)
