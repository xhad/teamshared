"""Redis edge rate limiting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import fakeredis.aioredis
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import BearerAuthMiddleware
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.identity.principal import Principal
from teamshared.server.rate_limit import (
    HttpRateLimitMiddleware,
    RateLimitLimits,
    RedisRateLimiter,
    email_bucket,
)


@pytest.fixture
def limiter() -> RedisRateLimiter:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisRateLimiter(
        "redis://unused",
        enabled=True,
        limits=RateLimitLimits(mint_per_minute=2, otp_send_per_minute=2, mcp_per_minute=2),
        client=client,
    )


@pytest.mark.asyncio
async def test_allow_fixed_window(limiter: RedisRateLimiter) -> None:
    first = await limiter.allow("test:bucket", limit=2, window_seconds=60)
    second = await limiter.allow("test:bucket", limit=2, window_seconds=60)
    third = await limiter.allow("test:bucket", limit=2, window_seconds=60)
    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after >= 1


@pytest.mark.asyncio
async def test_disabled_always_allows(limiter: RedisRateLimiter) -> None:
    limiter.enabled = False
    for _ in range(5):
        result = await limiter.allow("test:bucket", limit=1)
        assert result.allowed is True


def test_email_bucket_is_stable() -> None:
    assert email_bucket("User@Example.com") == email_bucket("user@example.com")
    assert email_bucket("a@b.co") != email_bucket("b@a.co")


def _mint_app(limiter: RedisRateLimiter) -> Starlette:
    async def mint(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/tokens/mint", mint, methods=["POST"])],
        middleware=[Middleware(HttpRateLimitMiddleware)],
    )
    app.state.rate_limiter = limiter
    return app


def test_mint_middleware_returns_429(limiter: RedisRateLimiter) -> None:
    client = TestClient(_mint_app(limiter))
    assert client.post("/tokens/mint").status_code == 200
    assert client.post("/tokens/mint").status_code == 200
    resp = client.post("/tokens/mint")
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limited"
    assert "Retry-After" in resp.headers


def _redemption_app(limiter: RedisRateLimiter) -> Starlette:
    async def root(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/", root, methods=["GET"]),
            Route("/get-token", root, methods=["GET"]),
            Route("/get-token/{invite}", root, methods=["GET"]),
            Route("/get-token/{invite}/{agent}", root, methods=["GET"]),
        ],
        middleware=[Middleware(HttpRateLimitMiddleware)],
    )
    app.state.rate_limiter = limiter
    return app


def test_root_invite_redemption_returns_429(limiter: RedisRateLimiter) -> None:
    client = TestClient(_redemption_app(limiter))
    assert client.get("/?invite=abc&agent=cursor").status_code == 200
    assert client.get("/?invite=abc&agent=cursor").status_code == 200
    resp = client.get("/?invite=abc&agent=cursor")
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limited"


def test_get_token_path_redemption_returns_429(limiter: RedisRateLimiter) -> None:
    client = TestClient(_redemption_app(limiter))
    assert client.get("/get-token/abc/cursor").status_code == 200
    assert client.get("/get-token/abc/cursor").status_code == 200
    assert client.get("/get-token/abc/cursor").status_code == 429


def test_plain_landing_and_form_pages_not_throttled(limiter: RedisRateLimiter) -> None:
    client = TestClient(_redemption_app(limiter))
    for _ in range(5):
        assert client.get("/").status_code == 200
        assert client.get("/get-token").status_code == 200


def _mcp_app(limiter: RedisRateLimiter) -> Starlette:
    async def ping(request: Request) -> JSONResponse:
        principal = getattr(request.state, "principal", None)
        return JSONResponse({"agent": principal.display if principal else None})

    principal = Principal(
        org_id=UUID("00000000-0000-0000-0000-000000000001"),
        type="agent",
        id=UUID("11111111-1111-1111-1111-111111111111"),
        display="cursor",
        roles=("agent",),
    )
    resolver = MagicMock(spec=PrincipalResolver)
    resolver.resolve = AsyncMock(return_value=principal)
    resolver.anonymous = AsyncMock(return_value=principal)

    app = Starlette(
        routes=[Route("/mcp/ping", ping, methods=["GET"])],
        middleware=[
            Middleware(BearerAuthMiddleware, resolver=resolver, auth_disabled=False),
            Middleware(HttpRateLimitMiddleware),
        ],
    )
    app.state.rate_limiter = limiter
    return app


def test_mcp_middleware_per_token(limiter: RedisRateLimiter) -> None:
    client = TestClient(_mcp_app(limiter))
    headers = {"Authorization": "Bearer tsk_test_secret"}
    assert client.get("/mcp/ping", headers=headers).status_code == 200
    assert client.get("/mcp/ping", headers=headers).status_code == 200
    assert client.get("/mcp/ping", headers=headers).status_code == 429
