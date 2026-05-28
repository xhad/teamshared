"""Working-memory tests, using fakeredis so they run without Redis installed."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio

from teamshared.memory import working as working_mod
from teamshared.memory.working import DISTILL_QUEUE_KEY, WorkingMemory


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
