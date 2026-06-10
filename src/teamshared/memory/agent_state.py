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

# Idle expiry for state keys: refreshed on every read/write, so only state
# untouched for this long is dropped. Bounds otherwise-unbounded keyspace growth.
STATE_DEFAULT_TTL_SECONDS = 180 * 24 * 3600
# Hard cap on one serialized value; state is bookkeeping, not bulk storage.
STATE_MAX_VALUE_BYTES = 64 * 1024

# Durable memories are scoped to a workspace/repo by carrying a normalized tag
# of the form ``repo:<slug>``. This rides the existing free-form ``tags``
# plumbing (no schema change) and lets recall boost the caller's current repo.
REPO_TAG_PREFIX = "repo:"
GITHUB_TAG_PREFIX = "github:"

_GITHUB_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)


def validate_repo(repo: str) -> str:
    repo = repo.strip()
    if not repo or not _REPO_PATTERN.fullmatch(repo):
        raise ValueError(
            "repo must be a non-empty workspace slug (alphanumeric, '.', '_', '-')"
        )
    return repo


def repo_tag(repo: str) -> str:
    """Return the canonical ``repo:<slug>`` tag for a workspace slug."""
    return f"{REPO_TAG_PREFIX}{validate_repo(repo)}"


def validate_github(github: str) -> str:
    github = github.strip()
    if not github or not _GITHUB_PATTERN.fullmatch(github):
        raise ValueError(
            "github must be owner/repo (e.g. xhad/teamshared)"
        )
    return github


def github_tag(github: str) -> str:
    """Return the canonical ``github:<owner>/<repo>`` tag for a GitHub remote."""
    return f"{GITHUB_TAG_PREFIX}{validate_github(github)}"


def validate_key(key: str) -> str:
    key = key.strip()
    if not key or not _KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "key must look like 'namespace/name' (lowercase letters, digits, '_', '-', '/')"
        )
    return key


def storage_key(state_id: str, repo: str, key: str, *, org: str | None = None) -> str:
    repo = validate_repo(repo)
    key = validate_key(key)
    if org:
        return f"agent-state:{org}:{state_id}:{repo}:{key}"
    return f"agent-state:{state_id}:{repo}:{key}"


class AgentStateStore:
    """Small JSON blob store keyed by (org, state_id, repo, key).

    ``org`` is the principal's org id (G2 tenant namespace). It defaults to
    ``None`` for backward-compatible callers, but the converged tool surface
    always passes it so client state is isolated per tenant.
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        ttl_seconds: int = STATE_DEFAULT_TTL_SECONDS,
        max_value_bytes: int = STATE_MAX_VALUE_BYTES,
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._max_value_bytes = max_value_bytes

    async def get(
        self, state_id: str, repo: str, key: str, *, org: str | None = None
    ) -> dict[str, Any] | None:
        redis_key = storage_key(state_id, repo, key, org=org)
        raw = await self._client.get(redis_key)
        if raw is None:
            return None
        if self._ttl_seconds > 0:
            # Reading is activity: keep live state alive (idle-expiry semantics).
            await self._client.expire(redis_key, self._ttl_seconds)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("stored agent state must be a JSON object")
        return parsed

    async def set(
        self, state_id: str, repo: str, key: str, value: dict[str, Any], *, org: str | None = None
    ) -> None:
        if not isinstance(value, dict):
            raise ValueError("value must be a JSON object")
        payload = json.dumps(value, separators=(",", ":"))
        if len(payload.encode("utf-8")) > self._max_value_bytes:
            raise ValueError(
                f"state value too large (> {self._max_value_bytes} bytes); "
                "store bulk data elsewhere and keep a pointer here"
            )
        redis_key = storage_key(state_id, repo, key, org=org)
        ex = self._ttl_seconds if self._ttl_seconds > 0 else None
        await self._client.set(redis_key, payload, ex=ex)
        log.info("agent_state_set", state_id=state_id, repo=repo, key=key, org=org)

    async def delete(
        self, state_id: str, repo: str, key: str, *, org: str | None = None
    ) -> bool:
        deleted = await self._client.delete(storage_key(state_id, repo, key, org=org))
        return bool(deleted)
