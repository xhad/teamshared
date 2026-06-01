"""Principal auth, rate limiting, and idempotency for the REST API.

Auth resolves a bearer token to a :class:`Principal` via the hashed API-key
store (or a JWT session). Rate limiting and idempotency are in-process here for
simplicity; a multi-instance deployment swaps the backing dict for Redis (the
interfaces are intentionally small).
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from teamshared.identity.api_keys import ApiKeyStore
from teamshared.identity.sessions import verify_session
from teamshared.logging import get_logger

log = get_logger(__name__)


class PrincipalAuthMiddleware(BaseHTTPMiddleware):
    """Resolve ``Authorization: Bearer`` to a Principal and bind request.state."""

    def __init__(
        self,
        app: ASGIApp,
        api_keys: ApiKeyStore,
        *,
        session_secret: str | None = None,
        public_paths: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(app)
        self.api_keys = api_keys
        self.session_secret = session_secret
        self.public_paths = public_paths

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = secrets.token_hex(8)
        if request.url.path in self.public_paths:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse(
                {"error": {"code": "missing_bearer_token", "message": "Authorization required",
                           "request_id": request.state.request_id}},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = header[len("bearer ") :].strip()
        principal = await self.api_keys.authenticate(token)
        if principal is None and self.session_secret:
            principal = verify_session(token, secret=self.session_secret)
        if principal is None:
            return JSONResponse(
                {"error": {"code": "invalid_token", "message": "Invalid or expired token",
                           "request_id": request.state.request_id}},
                status_code=401,
            )
        request.state.principal = principal
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-principal rate limit (in-process)."""

    def __init__(self, app: ASGIApp, *, limit: int = 120, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self._buckets: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return await call_next(request)
        key = f"{principal.org_id}:{principal.id}"
        count, window_start = self._buckets[key]
        now = time.monotonic()
        if now - window_start >= self.window:
            count, window_start = 0, now
        count += 1
        self._buckets[key] = (count, window_start)
        if count > self.limit:
            retry = int(self.window - (now - window_start))
            return JSONResponse(
                {"error": {"code": "rate_limited", "message": "Too many requests",
                           "request_id": getattr(request.state, "request_id", None)}},
                status_code=429,
                headers={"Retry-After": str(max(retry, 1))},
            )
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Replay-protect writes carrying an ``Idempotency-Key`` header (in-process)."""

    def __init__(self, app: ASGIApp, *, ttl_seconds: int = 600) -> None:
        super().__init__(app)
        self.ttl = ttl_seconds
        self._seen: dict[str, float] = {}

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        key = request.headers.get("idempotency-key")
        if not key or request.method not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)
        principal = getattr(request.state, "principal", None)
        scoped = f"{getattr(principal, 'org_id', '')}:{key}"
        now = time.monotonic()
        self._seen = {k: v for k, v in self._seen.items() if now - v < self.ttl}
        if scoped in self._seen:
            return JSONResponse(
                {"error": {"code": "idempotency_replay",
                           "message": "Request with this Idempotency-Key already processed",
                           "request_id": getattr(request.state, "request_id", None)}},
                status_code=409,
            )
        response: Response = await call_next(request)
        if response.status_code < 400:
            self._seen[scoped] = now
        return response
