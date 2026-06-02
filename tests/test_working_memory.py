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
    CURATE_PENDING_KEY,
    CURATE_QUEUE_KEY,
    DISTILL_QUEUE_KEY,
    WorkingMemory,
    _auto_session_key,
)

# Every working-memory key is org-namespaced post-G2; tests pin one org.
ORG = "00000000-0000-0000-0000-000000000001"


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
    sid = await memory.open_session(ORG, "cursor", topic="memory plan")
    assert sid.startswith("sess_")

    n = await memory.append_turn(ORG, sid, "user", "hello")
    assert n == 1
    n = await memory.append_turn(ORG, sid, "assistant", "hi there")
    assert n == 2

    turns = await memory.get_turns(ORG, sid)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert [t["content"] for t in turns] == ["hello", "hi there"]

    closed = await memory.close_session(ORG, sid, distill=True)
    assert closed["session_id"] == sid
    assert closed["turn_count"] == 2
    assert closed["distill_enqueued"] is True

    job_raw = await memory.client.lpop(DISTILL_QUEUE_KEY)
    assert job_raw is not None
    job = json.loads(job_raw)
    assert job["session_id"] == sid
    assert job["agent"] == "cursor"
    assert job["org_id"] == ORG
    assert job["turn_count"] == 2


async def test_append_to_closed_session_fails(memory: WorkingMemory) -> None:
    sid = await memory.open_session(ORG, "cursor")
    await memory.close_session(ORG, sid, distill=False)
    with pytest.raises(ValueError, match="closed"):
        await memory.append_turn(ORG, sid, "user", "late")


async def test_append_to_unknown_session_fails(memory: WorkingMemory) -> None:
    with pytest.raises(KeyError):
        await memory.append_turn(ORG, "sess_nope", "user", "x")


async def test_list_open_sessions_returns_recent(memory: WorkingMemory) -> None:
    sid1 = await memory.open_session(ORG, "cursor", topic="a")
    sid2 = await memory.open_session(ORG, "cursor", topic="b")
    sessions = await memory.list_open_sessions(ORG, "cursor", limit=10)
    ids = {s["session_id"] for s in sessions}
    assert {sid1, sid2}.issubset(ids)


async def test_recent_records_uses_latest_session(memory: WorkingMemory) -> None:
    sid = await memory.open_session(ORG, "cursor", topic="t")
    await memory.append_turn(ORG, sid, "user", "one")
    await memory.append_turn(ORG, sid, "assistant", "two")
    records = await memory.recent_records(ORG, "cursor", k=5)
    assert len(records) == 2
    assert records[0].pillar == "working"
    assert "[user] one" in records[0].content


async def test_working_memory_is_org_isolated(memory: WorkingMemory) -> None:
    other = "00000000-0000-0000-0000-0000000000ff"
    sid = await memory.open_session(ORG, "cursor", topic="t")
    await memory.append_turn(ORG, sid, "user", "secret")
    # The same agent in a different org sees none of the first org's sessions.
    assert await memory.list_open_sessions(other, "cursor") == []
    assert await memory.recent_records(other, "cursor", k=5) == []


async def test_close_without_distill_skips_queue(memory: WorkingMemory) -> None:
    sid = await memory.open_session(ORG, "cursor")
    await memory.append_turn(ORG, sid, "user", "x")
    await memory.close_session(ORG, sid, distill=False)
    assert await memory.client.llen(DISTILL_QUEUE_KEY) == 0


async def test_record_tool_call_reuses_one_session(memory: WorkingMemory) -> None:
    sid1 = await memory.record_tool_call(
        ORG, "cursor", "memory_recall(query=hi) -> ok", idle_seconds=1800, max_turns=200
    )
    sid2 = await memory.record_tool_call(
        ORG, "cursor", "memory_remember(content=x) -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid1 == sid2
    turns = await memory.get_turns(ORG, sid1)
    assert [t["role"] for t in turns] == ["tool", "tool"]
    assert "memory_recall" in turns[0]["content"]
    meta = await memory.get_metadata(ORG, sid1)
    assert meta["topic"] == AUTO_CAPTURE_TOPIC


async def test_record_tool_call_isolated_per_agent(memory: WorkingMemory) -> None:
    sid_cursor = await memory.record_tool_call(
        ORG, "cursor", "health() -> ok", idle_seconds=1800, max_turns=200
    )
    sid_codex = await memory.record_tool_call(
        ORG, "codex", "health() -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid_cursor != sid_codex


async def test_record_tool_call_rolls_over_when_idle(memory: WorkingMemory) -> None:
    sid1 = await memory.record_tool_call(
        ORG, "cursor", "first() -> ok", idle_seconds=1800, max_turns=200
    )
    # Force the pointer to look stale so the next call rolls the session over.
    pointer = json.loads(await memory.client.get(_auto_session_key(ORG, "cursor")))
    pointer["last_activity"] = 0
    await memory.client.set(_auto_session_key(ORG, "cursor"), json.dumps(pointer))

    sid2 = await memory.record_tool_call(
        ORG, "cursor", "second() -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid2 != sid1
    # The stale session was closed and enqueued for distillation.
    job_raw = await memory.client.lpop(DISTILL_QUEUE_KEY)
    assert job_raw is not None
    assert json.loads(job_raw)["session_id"] == sid1


async def test_record_tool_call_rolls_over_at_max_turns(memory: WorkingMemory) -> None:
    sid1 = await memory.record_tool_call(
        ORG, "cursor", "a() -> ok", idle_seconds=1800, max_turns=1
    )
    sid2 = await memory.record_tool_call(
        ORG, "cursor", "b() -> ok", idle_seconds=1800, max_turns=1
    )
    assert sid2 != sid1


async def test_record_turn_preserves_roles(memory: WorkingMemory) -> None:
    sid = await memory.record_turn(
        ORG, "cursor", "user", "what's in the brain?", idle_seconds=1800, max_turns=200
    )
    await memory.record_turn(
        ORG, "cursor", "assistant", "Here's what's stored.", idle_seconds=1800, max_turns=200
    )
    await memory.record_turn(
        ORG, "cursor", "tool", "memory_recall(query=x) -> ok", idle_seconds=1800, max_turns=200
    )
    turns = await memory.get_turns(ORG, sid)
    assert [t["role"] for t in turns] == ["user", "assistant", "tool"]
    assert turns[0]["content"] == "what's in the brain?"


async def test_record_turn_shares_session_with_tool_calls(memory: WorkingMemory) -> None:
    sid_turn = await memory.record_turn(
        ORG, "cursor", "user", "hi", idle_seconds=1800, max_turns=200
    )
    sid_tool = await memory.record_tool_call(
        ORG, "cursor", "memory_recall(query=hi) -> ok", idle_seconds=1800, max_turns=200
    )
    assert sid_turn == sid_tool


# --------------------------------------------------------------------------- #
# Curate queue + debounce (Phase 4b)
# --------------------------------------------------------------------------- #
async def test_mark_subject_dirty_enqueues_on_threshold(memory: WorkingMemory) -> None:
    # Below threshold: nothing queued yet.
    assert await memory.mark_subject_dirty(ORG, "infra", threshold=3) is False
    assert await memory.mark_subject_dirty(ORG, "infra", threshold=3) is False
    assert int(await memory.client.llen(CURATE_QUEUE_KEY)) == 0
    # The third new fact crosses the threshold and enqueues.
    assert await memory.mark_subject_dirty(ORG, "infra", threshold=3) is True
    assert int(await memory.client.llen(CURATE_QUEUE_KEY)) == 1


async def test_mark_subject_dirty_ignores_blank_subject(memory: WorkingMemory) -> None:
    assert await memory.mark_subject_dirty(ORG, "   ", threshold=1) is False
    assert int(await memory.client.llen(CURATE_QUEUE_KEY)) == 0


async def test_enqueue_curate_dedupes_pending(memory: WorkingMemory) -> None:
    assert await memory.enqueue_curate(ORG, "infra") is True
    # Already pending: not queued again.
    assert await memory.enqueue_curate(ORG, "infra") is False
    assert int(await memory.client.llen(CURATE_QUEUE_KEY)) == 1


async def test_pop_curate_job_clears_pending_and_allows_requeue(memory: WorkingMemory) -> None:
    await memory.enqueue_curate(ORG, "infra")
    job = await memory.pop_curate_job(timeout=1)
    assert job is not None
    assert job["subject"] == "infra"
    assert job["org_id"] == ORG
    # Pending flag cleared, so the subject can be enqueued for a fresh pass.
    assert int(await memory.client.scard(CURATE_PENDING_KEY)) == 0
    assert await memory.enqueue_curate(ORG, "infra") is True


# --------------------------------------------------------------------------- #
# Console sign-in OTP
# --------------------------------------------------------------------------- #
EMAIL = "owner@example.com"


async def test_login_otp_roundtrip_is_single_use(memory: WorkingMemory) -> None:
    await memory.set_login_otp(EMAIL, "123456", ttl=30)
    assert await memory.verify_login_otp(EMAIL, "123456") is True
    # Consumed on success: a replay fails.
    assert await memory.verify_login_otp(EMAIL, "123456") is False


async def test_login_otp_email_is_case_insensitive(memory: WorkingMemory) -> None:
    await memory.set_login_otp("Owner@Example.com ", "654321", ttl=30)
    assert await memory.verify_login_otp("owner@example.com", "654321") is True


async def test_login_otp_unknown_email_returns_false(memory: WorkingMemory) -> None:
    assert await memory.verify_login_otp("nobody@example.com", "000000") is False


async def test_login_otp_caps_wrong_attempts(memory: WorkingMemory) -> None:
    await memory.set_login_otp(EMAIL, "111111", ttl=30, max_attempts=2)
    assert await memory.verify_login_otp(EMAIL, "999999") is False  # attempt 1
    assert await memory.verify_login_otp(EMAIL, "888888") is False  # attempt 2 -> cap
    # Even the correct code is now rejected; the code was burned.
    assert await memory.verify_login_otp(EMAIL, "111111") is False


async def test_login_otp_sets_ttl(memory: WorkingMemory) -> None:
    await memory.set_login_otp(EMAIL, "222222", ttl=30)
    ttl = await memory.client.ttl(working_mod._otp_key(EMAIL))
    assert 0 < ttl <= 30


async def test_set_login_otp_overwrites_prior_code(memory: WorkingMemory) -> None:
    await memory.set_login_otp(EMAIL, "111111", ttl=30)
    await memory.set_login_otp(EMAIL, "222222", ttl=30)
    assert await memory.verify_login_otp(EMAIL, "111111") is False
    assert await memory.verify_login_otp(EMAIL, "222222") is True
