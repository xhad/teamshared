"""Per-org quotas + backpressure backed by Redis counters.

Counters roll over daily. Exceeding a limit raises :class:`QuotaExceeded`,
which the caller surfaces as HTTP 429 / job backpressure. Embedding spend is
the primary cost lever, so it gets a first-class resource.
"""

from __future__ import annotations

from uuid import UUID

import redis.asyncio as redis

_DEFAULT_LIMITS: dict[str, int] = {
    "embed_calls": 50_000,
    "memory_writes": 100_000,
    "search_calls": 200_000,
}


class QuotaExceeded(Exception):  # noqa: N818 - idiomatic name; not an *Error
    def __init__(self, org_id: UUID, resource: str, limit: int) -> None:
        self.org_id = org_id
        self.resource = resource
        self.limit = limit
        super().__init__(f"org {org_id} exceeded {resource} quota ({limit}/day)")


class QuotaManager:
    def __init__(self, client: redis.Redis, *, limits: dict[str, int] | None = None) -> None:
        self.client = client
        self.limits = {**_DEFAULT_LIMITS, **(limits or {})}

    def _key(self, org_id: UUID, resource: str) -> str:
        return f"quota:{org_id}:{resource}"

    async def consume(self, org_id: UUID, resource: str, amount: int = 1) -> int:
        """Increment usage; raise if it would exceed the daily limit."""
        limit = self.limits.get(resource)
        key = self._key(org_id, resource)
        new_value = int(await self.client.incrby(key, amount))
        if new_value == amount:
            await self.client.expire(key, 86400)
        if limit is not None and new_value > limit:
            raise QuotaExceeded(org_id, resource, limit)
        return new_value

    async def usage(self, org_id: UUID, resource: str) -> int:
        raw = await self.client.get(self._key(org_id, resource))
        return int(raw) if raw else 0
