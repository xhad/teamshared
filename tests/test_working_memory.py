"""Working-memory tests, using fakeredis so they run without Redis installed."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio

from teamshared.memory import working as working_mod
from teamshared.memory.working import (
    AUTO_CAPTURE_TOPIC,
    DISTILL_QUEUE_KEY,
    WorkingMemory,
    _auto_session_key,
)


@pytest_asyncio.fixture
async def memory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[WorkingMemory]:
    """Yield a :class:`WorkingMemory` backed by an in-memory fake Redis."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _from_url(url: str, **kwargs: object) -> fakeredis.aioredis.FakeRedis:
        return fake

    monkeypatch.setattr(working_mod.redis, "from_url", _from_url)

    mem = WorkingMemory("redis://fake", default_ttl=60)
    await mem.connect()
    try:
        yield mem
    finally:
        await mem.close()


async def test_open_append_close_session(memory: WorkingMemory) -> None:
    sid = await memory.open_session("cursor", topic="memory plan")
    assert sid.startswith("sess_")

    n = await memory.append_turn(sid, "user", "hello")
    assert n == 1
    n = await memory.append_turn(sid, "assistant", "hi there")
    assert n == 2

    turns = await memory.get_turns(sid)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert [t["content"] for t in turns] == ["hello", "hi there"]

    closed = await memory.close_session(sid, distill=True)
    assert closed["session_id"] == sid
    assert closed["turn_count"] == 2
    assert closed["distill_enqueued"] is True

    job_raw = await memory.client.lpop(DISTILL_QUEUE_KEY)
    assert job_raw is not None
    job = json.loads(job_raw)
    assert job["session_id"] == sid
    assert job["agent"] == "cursor"
    assert job["turn_count"] == 2


async def test_append_to_closed_session_fails(memory: WorkingMemory) -> None:
    sid = await memory.open_session("cursor")
    await memory.close_session(sid, distill=False)
    with pytest.raises(ValueError, match="closed"):
        await memory.append_turn(sid, "user", "late")


async def test_append_to_unknown_session_fails(memory: WorkingMemory) -> None:
    with pytest.raises(KeyError):
        await memory.append_turn("sess_nope", "user", "x")


async def test_list_open_sessions_returns_recent(memory: WorkingMemory) -> None:
    sid1 = await memory.open_session("cursor", topic="a")
    sid2 = await memory.open_session("cursor", topic="b")
    sessions = await memory.list_open_sessions("cursor", limit=10)
    ids = {s["session_id"] for s in sessions}
    assert {sid1, sid2}.issubset(ids)


async def test_recent_records_uses_latest_session(memory: WorkingMemory) -> None:
    sid = await memory.open_session("cursor", topic="t")
    await memory.append_turn(sid, "user", "one")
    await memory.append_turn(sid, "assistant", "two")
    records = await memory.recent_records("cursor", k=5)
    assert len(records) == 2
    assert records[0].pillar == "working"
    assert "[user] one" in records[0].content


async def test_close_without_distill_skips_queue(memory: WorkingMemory) -> None:
    sid = await memory.open_session("cursor")
    await memory.append_turn(sid, "user", "x")
    await memory.close_session(sid, distill=False)
    assert await memory.client.llen(DISTILL_QUEUE_KEY) == 0


async def test_record_tool_call_reuses_one_session(memory: WorkingMemory) -> None:
    sid1 = await memory.record_tool_call(
        "cursor", "memory_recall(query=hi) -> ok", idle_seconds=1800, max_turns=200
    )
    sid2 = await memory.record_tool_call(
        "cursor", "memory_remember(content=x) -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid1 == sid2
    turns = await memory.get_turns(sid1)
    assert [t["role"] for t in turns] == ["tool", "tool"]
    assert "memory_recall" in turns[0]["content"]
    meta = await memory.get_metadata(sid1)
    assert meta["topic"] == AUTO_CAPTURE_TOPIC


async def test_record_tool_call_isolated_per_agent(memory: WorkingMemory) -> None:
    sid_cursor = await memory.record_tool_call(
        "cursor", "health() -> ok", idle_seconds=1800, max_turns=200
    )
    sid_codex = await memory.record_tool_call(
        "codex", "health() -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid_cursor != sid_codex


async def test_record_tool_call_rolls_over_when_idle(memory: WorkingMemory) -> None:
    sid1 = await memory.record_tool_call(
        "cursor", "first() -> ok", idle_seconds=1800, max_turns=200
    )
    # Force the pointer to look stale so the next call rolls the session over.
    pointer = json.loads(await memory.client.get(_auto_session_key("cursor")))
    pointer["last_activity"] = 0
    await memory.client.set(_auto_session_key("cursor"), json.dumps(pointer))

    sid2 = await memory.record_tool_call(
        "cursor", "second() -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid2 != sid1
    # The stale session was closed and enqueued for distillation.
    job_raw = await memory.client.lpop(DISTILL_QUEUE_KEY)
    assert job_raw is not None
    assert json.loads(job_raw)["session_id"] == sid1


async def test_record_tool_call_rolls_over_at_max_turns(memory: WorkingMemory) -> None:
    sid1 = await memory.record_tool_call(
        "cursor", "a() -> ok", idle_seconds=1800, max_turns=1
    )
    sid2 = await memory.record_tool_call(
        "cursor", "b() -> ok", idle_seconds=1800, max_turns=1
    )
    assert sid2 != sid1


async def test_record_turn_preserves_roles(memory: WorkingMemory) -> None:
    sid = await memory.record_turn(
        "cursor", "user", "what's in the brain?", idle_seconds=1800, max_turns=200
    )
    await memory.record_turn(
        "cursor", "assistant", "Here's what's stored.", idle_seconds=1800, max_turns=200
    )
    await memory.record_turn(
        "cursor", "tool", "memory_recall(query=x) -> ok", idle_seconds=1800, max_turns=200
    )
    turns = await memory.get_turns(sid)
    assert [t["role"] for t in turns] == ["user", "assistant", "tool"]
    assert turns[0]["content"] == "what's in the brain?"


async def test_record_turn_shares_session_with_tool_calls(memory: WorkingMemory) -> None:
    sid_turn = await memory.record_turn(
        "cursor", "user", "hi", idle_seconds=1800, max_turns=200
    )
    sid_tool = await memory.record_tool_call(
        "cursor", "memory_recall(query=hi) -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid_turn == sid_tool
