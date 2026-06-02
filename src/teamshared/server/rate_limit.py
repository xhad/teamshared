"""Redis-backed fixed-window rate limits for the HTTP edge.

Used for token mint (per client IP), console OTP (per email), and MCP/bearer
tool traffic (per org principal). When Redis is unreachable the limiter fails
open (logs a warning, allows the request) so a Redis outage does not brick the
server; mint/OTP abuse is the main threat surface this stage targets.

The ``/v1`` REST stack still uses in-process :class:`RateLimitMiddleware` in
``server.api.middleware``; swapping that to Redis is Stage 4.2.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import redis.asyncio as redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.metrics import METRICS
from teamshared.server.route_policy import RouteClass, classify_path

log = get_logger(__name__)

_KEY_PREFIX = "ratelimit:"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    retry_after: int


@dataclass(frozen=True)
class RateLimitLimits:
    mint_per_minute: int = 10
    otp_send_per_minute: int = 3
    otp_verify_per_minute: int = 5
    mcp_per_minute: int = 120


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours ``X-Forwarded-For`` when present)."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def email_bucket(email: str) -> str:
    """Stable short bucket id for an email (no PII in Redis keys)."""
    normalized = email.strip().lower()
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:24]
    return digest


class RedisRateLimiter:
    """Fixed-window counter in Redis (INCR + EXPIRE on first hit)."""

    def __init__(
        self,
        redis_url: str,
        *,
        enabled: bool = True,
        limits: RateLimitLimits | None = None,
        client: redis.Redis | None = None,
    ) -> None:
        self._url = redis_url
        self.enabled = enabled
        self.limits = limits or RateLimitLimits()
        self._client = client

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def allow(
        self,
        bucket: str,
        *,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitResult:
        """Return whether ``bucket`` may proceed within the window."""
        if not self.enabled or limit <= 0:
            return RateLimitResult(allowed=True, count=0, retry_after=0)
        if self._client is None:
            await self.connect()
        assert self._client is not None
        key = f"{_KEY_PREFIX}{bucket}"
        try:
            count = int(await self._client.incr(key))
            if count == 1:
                await self._client.expire(key, window_seconds)
            ttl = await self._client.ttl(key)
            retry_after = max(int(ttl), 1) if ttl and ttl > 0 else window_seconds
            if count > limit:
                return RateLimitResult(allowed=False, count=count, retry_after=retry_after)
            return RateLimitResult(allowed=True, count=count, retry_after=0)
        except Exception as exc:
            log.warning("rate_limit_redis_error", bucket=bucket, error=str(exc))
            return RateLimitResult(allowed=True, count=0, retry_after=0)

    async def check_mint(self, request: Request) -> RateLimitResult:
        ip = client_ip(request)
        invite = request.path_params.get("invite", "")
        suffix = f":{invite}" if invite else ""
        return await self.allow(
            f"mint:ip:{ip}{suffix}",
            limit=self.limits.mint_per_minute,
        )

    async def check_otp_send(self, email: str) -> RateLimitResult:
        return await self.allow(
            f"otp:send:{email_bucket(email)}",
            limit=self.limits.otp_send_per_minute,
        )

    async def check_otp_verify(self, email: str) -> RateLimitResult:
        return await self.allow(
            f"otp:verify:{email_bucket(email)}",
            limit=self.limits.otp_verify_per_minute,
        )

    async def check_mcp(self, principal: Principal | None, request: Request) -> RateLimitResult:
        if principal is not None:
            bucket = f"mcp:{principal.org_id}:{principal.type}:{principal.id}"
        else:
            header = request.headers.get("authorization", "")
            token_prefix = header[7:15] if header.lower().startswith("bearer ") else "anon"
            bucket = f"mcp:anon:{token_prefix}"
        return await self.allow(bucket, limit=self.limits.mcp_per_minute)


def rate_limit_response(
    result: RateLimitResult,
    *,
    request_id: str | None = None,
) -> JSONResponse:
    METRICS.rate_limited.inc()
    return JSONResponse(
        {
            "error": "rate_limited",
            "retry_after": result.retry_after,
            "request_id": request_id,
        },
        status_code=429,
        headers={"Retry-After": str(max(result.retry_after, 1))},
    )


class HttpRateLimitMiddleware(BaseHTTPMiddleware):
    """Edge rate limits for mint and MCP/bearer paths (OTP uses handler helpers)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    def _limiter(self, request: Request) -> RedisRateLimiter | None:
        return getattr(request.app.state, "rate_limiter", None)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        limiter = self._limiter(request)
        if limiter is None or not limiter.enabled:
            return await call_next(request)

        path = request.url.path
        route_class = classify_path(path)
        method = request.method.upper()

        if route_class == RouteClass.PUBLIC_MINT and method == "POST":
            result = await limiter.check_mint(request)
            if not result.allowed:
                return rate_limit_response(
                    result, request_id=getattr(request.state, "request_id", None)
                )

        if route_class == RouteClass.MCP_BEARER:
            principal = getattr(request.state, "principal", None)
            result = await limiter.check_mcp(principal, request)
            if not result.allowed:
                return rate_limit_response(
                    result, request_id=getattr(request.state, "request_id", None)
                )

        return await call_next(request)


async def enforce_otp_send(limiter: RedisRateLimiter, email: str) -> JSONResponse | None:
    """Return a 429 response when the send limit is exceeded, else ``None``."""
    result = await limiter.check_otp_send(email)
    if not result.allowed:
        return rate_limit_response(result)
    return None


async def enforce_otp_verify(limiter: RedisRateLimiter, email: str) -> JSONResponse | None:
    """Return a 429 response when the verify limit is exceeded, else ``None``."""
    result = await limiter.check_otp_verify(email)
    if not result.allowed:
        return rate_limit_response(result)
    return None
