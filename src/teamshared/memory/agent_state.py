"""Redis-backed opaque JSON state scoped by bearer token and repo.

Used for client-side bookkeeping (e.g. continual-learning cadence/index) that
should follow the authenticated token across machines without polluting git.
"""

from __future__ import annotations

import json
import re
from typing import Any

import redis.asyncio as redis

from teamshared.logging import get_logger

log = get_logger(__name__)

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)*$")


def validate_repo(repo: str) -> str:
    repo = repo.strip()
    if not repo or not _REPO_PATTERN.fullmatch(repo):
        raise ValueError(
            "repo must be a non-empty workspace slug (alphanumeric, '.', '_', '-')"
        )
    return repo


def validate_key(key: str) -> str:
    key = key.strip()
    if not key or not _KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "key must look like 'namespace/name' (lowercase letters, digits, '_', '-', '/')"
        )
    return key


def storage_key(token_prefix: str, repo: str, key: str) -> str:
    repo = validate_repo(repo)
    key = validate_key(key)
    return f"agent-state:{token_prefix}:{repo}:{key}"


class AgentStateStore:
    """Small JSON blob store keyed by (token_prefix, repo, key)."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def get(self, token_prefix: str, repo: str, key: str) -> dict[str, Any] | None:
        raw = await self._client.get(storage_key(token_prefix, repo, key))
        if raw is None:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("stored agent state must be a JSON object")
        return parsed

    async def set(self, token_prefix: str, repo: str, key: str, value: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise ValueError("value must be a JSON object")
        redis_key = storage_key(token_prefix, repo, key)
        await self._client.set(redis_key, json.dumps(value, separators=(",", ":")))
        log.info("agent_state_set", token_prefix=token_prefix, repo=repo, key=key)

    async def delete(self, token_prefix: str, repo: str, key: str) -> bool:
        deleted = await self._client.delete(storage_key(token_prefix, repo, key))
        return bool(deleted)
