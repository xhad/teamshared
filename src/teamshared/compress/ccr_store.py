"""Compress-Cache-Retrieve: store originals in Redis for on-demand expansion."""

from __future__ import annotations

import hashlib
from uuid import UUID

import redis.asyncio as redis

from teamshared.logging import get_logger

log = get_logger(__name__)

_KEY_PREFIX = "teamshared:ccr"


def _ref(org_scope: str, digest: str) -> str:
    return f"ccr_{org_scope[:8]}_{digest[:16]}"


class CcrStore:
    """Org-scoped (or ``system``) Redis cache of pre-compression content."""

    def __init__(self, client: redis.Redis, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl = ttl_seconds

    def _key(self, org_scope: str, ref: str) -> str:
        return f"{_KEY_PREFIX}:{org_scope}:{ref}"

    async def put(self, org_scope: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        ref = _ref(org_scope, digest)
        key = self._key(org_scope, ref)
        existing = await self._client.get(key)
        if existing is not None:
            return ref
        await self._client.setex(key, self._ttl, content)
        return ref

    async def get(self, org_scope: str, ref: str) -> str | None:
        if not ref.startswith("ccr_"):
            return None
        raw = await self._client.get(self._key(org_scope, ref))
        if raw is None:
            return None
        return raw if isinstance(raw, str) else raw.decode("utf-8")


def org_scope_from_id(org_id: UUID | str | None) -> str:
    if org_id is None:
        return "system"
    return str(org_id)
