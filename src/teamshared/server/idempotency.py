"""Redis-backed idempotency for mutating HTTP requests (Stage 4.2).

``SET NX`` with TTL dedupes ``Idempotency-Key`` across server instances. On
handler failure (status >= 400) the key is deleted so clients may retry.
When Redis is unreachable the guard fails open (logs, allows the request).
"""

from __future__ import annotations

import redis.asyncio as redis

from teamshared.logging import get_logger

log = get_logger(__name__)

_KEY_PREFIX = "idempotency:"


class RedisIdempotencyGuard:
    """Claim/release idempotency scopes in Redis."""

    def __init__(
        self,
        redis_url: str,
        *,
        enabled: bool = True,
        ttl_seconds: int = 600,
        client: redis.Redis | None = None,
    ) -> None:
        self._url = redis_url
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._owns_client = client is None

    async def connect(self, *, client: redis.Redis | None = None) -> None:
        if client is not None:
            self._client = client
            self._owns_client = False
            return
        if self._client is not None:
            return
        self._client = redis.from_url(self._url, decode_responses=True)
        self._owns_client = True

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
        self._client = None
        self._owns_client = False

    async def claim(self, scoped_key: str) -> bool:
        """Return True if this request may proceed (first claimant)."""
        if not self.enabled:
            return True
        if self._client is None:
            await self.connect()
        assert self._client is not None
        key = f"{_KEY_PREFIX}{scoped_key}"
        try:
            return bool(
                await self._client.set(key, "1", nx=True, ex=self.ttl_seconds)
            )
        except Exception as exc:
            log.warning("idempotency_redis_error", scoped_key=scoped_key, error=str(exc))
            return True

    async def release(self, scoped_key: str) -> None:
        """Drop a claim so the same key can be retried after a failed write."""
        if not self.enabled or self._client is None:
            return
        key = f"{_KEY_PREFIX}{scoped_key}"
        try:
            await self._client.delete(key)
        except Exception as exc:
            log.warning("idempotency_redis_release_error", scoped_key=scoped_key, error=str(exc))
