"""Bearer-token auth for the HTTP/MCP surface.

:class:`BearerAuthMiddleware` resolves ``Authorization: Bearer`` tokens through
:class:`~teamshared.identity.legacy_bridge.PrincipalResolver` (``tsk_*`` API keys
and console session JWTs). Resolved identity is exposed on
``request.state.agent`` / ``request.state.principal`` and via contextvars for
tool handlers.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

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


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate ``Authorization: Bearer <token>`` via :class:`PrincipalResolver`.

    - Public paths skip bearer validation (see :mod:`route_policy`).
    - If ``auth_disabled`` is True, a synthetic ``anonymous`` identity is bound
      (useful for local development / tests).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resolver: PrincipalResolver,
        auth_disabled: bool = False,
    ) -> None:
        super().__init__(app)
        self.auth_disabled = auth_disabled
        self.resolver = resolver

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if outer_middleware_skips_bearer(path):
            return await call_next(request)

        identity: AgentIdentity | None = None
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

        principal = await self._resolve_principal(token)
        if not self.auth_disabled and principal is None:
            METRICS.auth_rejected.inc(reason="invalid_token")
            log.warning("auth_rejected", token_prefix=(token or "")[:8])
            return JSONResponse({"error": "invalid_token"}, status_code=401)

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

    async def _resolve_principal(self, token: str | None) -> Principal | None:
        try:
            if self.auth_disabled:
                return await self.resolver.anonymous()
            if token is None:
                return None
            return await self.resolver.resolve(token)
        except Exception as exc:  # resolution must not 500 the request
            log.warning("principal_resolution_failed", error=str(exc))
            return None
