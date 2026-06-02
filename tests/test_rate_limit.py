"""Redis edge rate limiting."""

from __future__ import annotations

from pathlib import Path

import fakeredis.aioredis
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import BearerAuthMiddleware, TokenStore
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


def _mcp_app(store: TokenStore, limiter: RedisRateLimiter) -> Starlette:
    async def ping(request: Request) -> JSONResponse:
        principal = getattr(request.state, "principal", None)
        return JSONResponse({"agent": principal.display if principal else None})

    app = Starlette(
        routes=[Route("/mcp/ping", ping, methods=["GET"])],
        middleware=[
            Middleware(BearerAuthMiddleware, store=store, auth_disabled=False),
            Middleware(HttpRateLimitMiddleware),
        ],
    )
    app.state.rate_limiter = limiter
    return app


def test_mcp_middleware_per_token(tmp_path: Path, limiter: RedisRateLimiter) -> None:
    store = TokenStore(tmp_path / "tokens.json", legacy_mint_enabled=True)
    token = store.mint("cursor")
    client = TestClient(_mcp_app(store, limiter))
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/mcp/ping", headers=headers).status_code == 200
    assert client.get("/mcp/ping", headers=headers).status_code == 200
    assert client.get("/mcp/ping", headers=headers).status_code == 429
