"""Principal auth, rate limiting, and idempotency for the REST API.

Auth resolves a bearer token to a :class:`Principal` via the hashed API-key
store (or a JWT session). Rate limiting and idempotency use Redis when
``app.state.rate_limiter`` / ``app.state.idempotency_guard`` are set (multi-
instance safe); otherwise they fall back to in-process dicts for isolated tests.
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
from teamshared.identity.principal import Principal
from teamshared.identity.sessions import verify_session
from teamshared.logging import get_logger
from teamshared.metrics import METRICS
from teamshared.server.idempotency import RedisIdempotencyGuard
from teamshared.server.rate_limit import RedisRateLimiter

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


def _v1_rate_limit_response(result, request: Request) -> JSONResponse:
    METRICS.rate_limited.inc()
    return JSONResponse(
        {
            "error": {
                "code": "rate_limited",
                "message": "Too many requests",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
        status_code=429,
        headers={"Retry-After": str(max(result.retry_after, 1))},
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-principal rate limit (Redis when wired, else in-process)."""

    def __init__(self, app: ASGIApp, *, limit: int = 120, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self._buckets: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def _limiter(self, request: Request) -> RedisRateLimiter | None:
        return getattr(request.app.state, "rate_limiter", None)

    async def _check_in_process(self, principal: Principal) -> JSONResponse | None:
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
                           "request_id": None}},
                status_code=429,
                headers={"Retry-After": str(max(retry, 1))},
            )
        return None

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return await call_next(request)

        limiter = self._limiter(request)
        if limiter is not None and limiter.enabled:
            result = await limiter.check_v1(principal)
            if not result.allowed:
                return _v1_rate_limit_response(result, request)

        if limiter is None or not limiter.enabled:
            blocked = await self._check_in_process(principal)
            if blocked is not None:
                METRICS.rate_limited.inc()
                return blocked

        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Replay-protect writes carrying an ``Idempotency-Key`` header."""

    def __init__(self, app: ASGIApp, *, ttl_seconds: int = 600) -> None:
        super().__init__(app)
        self.ttl = ttl_seconds
        self._seen: dict[str, float] = {}

    def _guard(self, request: Request) -> RedisIdempotencyGuard | None:
        return getattr(request.app.state, "idempotency_guard", None)

    @staticmethod
    def _scoped_key(principal: object | None, idem_key: str) -> str:
        org_id = getattr(principal, "org_id", "")
        return f"v1:{org_id}:{idem_key}"

    def _replay_response(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "idempotency_replay",
                       "message": "Request with this Idempotency-Key already processed",
                       "request_id": getattr(request.state, "request_id", None)}},
            status_code=409,
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        key = request.headers.get("idempotency-key")
        if not key or request.method not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)

        principal = getattr(request.state, "principal", None)
        scoped = self._scoped_key(principal, key)
        guard = self._guard(request)

        if guard is not None and guard.enabled:
            if not await guard.claim(scoped):
                return self._replay_response(request)
            response: Response = await call_next(request)
            if response.status_code >= 400:
                await guard.release(scoped)
            return response

        now = time.monotonic()
        self._seen = {k: v for k, v in self._seen.items() if now - v < self.ttl}
        if scoped in self._seen:
            return self._replay_response(request)
        response = await call_next(request)
        if response.status_code < 400:
            self._seen[scoped] = now
        return response
