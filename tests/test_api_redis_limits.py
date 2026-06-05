"""Redis-backed /v1 rate limit and idempotency (Stage 4.2)."""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.identity.principal import Principal
from teamshared.server.api.middleware import (
    IdempotencyMiddleware,
    PrincipalAuthMiddleware,
    RateLimitMiddleware,
)
from teamshared.server.idempotency import RedisIdempotencyGuard
from teamshared.server.rate_limit import RateLimitLimits, RedisRateLimiter


class _StubKeys:
    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def authenticate(self, token: str) -> Principal | None:
        return self._principal if token == "good" else None


def _principal() -> Principal:
    return Principal(org_id=uuid.uuid4(), type="user", id=uuid.uuid4())


@pytest.fixture
def limiter() -> RedisRateLimiter:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisRateLimiter(
        "redis://unused",
        enabled=True,
        limits=RateLimitLimits(v1_per_minute=2),
        client=client,
    )


@pytest.fixture
def guard() -> RedisIdempotencyGuard:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisIdempotencyGuard("redis://unused", enabled=True, ttl_seconds=60, client=client)


def _v1_app(limiter: RedisRateLimiter, guard: RedisIdempotencyGuard) -> Starlette:
    principal = _principal()
    call_count = {"n": 0}

    async def mutate(request: Request) -> JSONResponse:
        call_count["n"] += 1
        return JSONResponse({"ok": True, "n": call_count["n"]})

    app = Starlette(
        routes=[Route("/v1/x", mutate, methods=["POST"])],
        middleware=[
            Middleware(PrincipalAuthMiddleware, api_keys=_StubKeys(principal)),
            Middleware(RateLimitMiddleware, limit=99, window_seconds=60),
            Middleware(IdempotencyMiddleware),
        ],
    )
    app.state.rate_limiter = limiter
    app.state.idempotency_guard = guard
    return app


def test_v1_rate_limit_redis_trips(limiter: RedisRateLimiter, guard: RedisIdempotencyGuard) -> None:
    client = TestClient(_v1_app(limiter, guard))
    headers = {"Authorization": "Bearer good"}
    assert client.post("/v1/x", headers=headers).status_code == 200
    assert client.post("/v1/x", headers=headers).status_code == 200
    resp = client.post("/v1/x", headers=headers)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"


def test_v1_idempotency_redis_replay(limiter: RedisRateLimiter, guard: RedisIdempotencyGuard) -> None:
    client = TestClient(_v1_app(limiter, guard))
    headers = {"Authorization": "Bearer good", "Idempotency-Key": "idem-1"}
    first = client.post("/v1/x", headers=headers)
    second = client.post("/v1/x", headers=headers)
    assert first.status_code == 200
    assert first.json()["n"] == 1
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_replay"


@pytest.mark.asyncio
async def test_idempotency_release_on_failure(guard: RedisIdempotencyGuard) -> None:
    scoped = "v1:test-org:retry-key"
    assert await guard.claim(scoped) is True
    await guard.release(scoped)
    assert await guard.claim(scoped) is True
