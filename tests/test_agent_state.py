"""Tests for Redis-backed agent state (token + repo scoped)."""

from __future__ import annotations

import pytest

from teamshared.memory.agent_state import AgentStateStore, validate_key, validate_repo


@pytest.fixture
async def store() -> AgentStateStore:
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AgentStateStore(client)


async def test_agent_state_round_trip(store: AgentStateStore) -> None:
    repo = validate_repo("Users-chad-code-sapien-teamshared")
    key = validate_key("continual-learning/index")
    payload = {"version": 1, "transcripts": {"abc": {"mtime": 1, "processed_at": "now"}}}

    assert await store.get("tok12345", repo, key) is None
    await store.set("tok12345", repo, key, payload)
    assert await store.get("tok12345", repo, key) == payload


async def test_agent_state_isolated_by_token_and_repo(store: AgentStateStore) -> None:
    await store.set("tok_a", "repo-one", "continual-learning/cadence", {"turns": 1})
    await store.set("tok_b", "repo-one", "continual-learning/cadence", {"turns": 2})
    await store.set("tok_a", "repo-two", "continual-learning/cadence", {"turns": 3})

    assert (await store.get("tok_a", "repo-one", "continual-learning/cadence"))["turns"] == 1
    assert (await store.get("tok_b", "repo-one", "continual-learning/cadence"))["turns"] == 2
    assert (await store.get("tok_a", "repo-two", "continual-learning/cadence"))["turns"] == 3


async def test_agent_state_delete(store: AgentStateStore) -> None:
    await store.set("tok_a", "repo-one", "continual-learning/cadence", {"turns": 1})
    assert await store.delete("tok_a", "repo-one", "continual-learning/cadence") is True
    assert await store.get("tok_a", "repo-one", "continual-learning/cadence") is None
    assert await store.delete("tok_a", "repo-one", "continual-learning/cadence") is False


def test_validate_repo_rejects_empty() -> None:
    with pytest.raises(ValueError):
        validate_repo("")


def test_validate_key_rejects_uppercase() -> None:
    with pytest.raises(ValueError):
        validate_key("Continual-Learning/Index")
