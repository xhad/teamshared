"""Stream queue + quotas using fakeredis (no real Redis required)."""

from __future__ import annotations

import uuid

import fakeredis
import fakeredis.aioredis
import pytest

from teamshared.queue.quotas import QuotaExceeded, QuotaManager
from teamshared.queue.streams import StreamQueue


async def _client() -> fakeredis.aioredis.FakeRedis:
    # Fresh server per call so tests don't share stream/group state.
    return fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer())


async def test_enqueue_read_ack() -> None:
    q = StreamQueue(await _client())
    await q.ensure_group("jobs", "workers")
    msg_id = await q.enqueue("jobs", {"task": "distill", "session": "s1"}, org_id="o1")
    assert msg_id is not None
    jobs = await q.read("jobs", "workers", "c1", block_ms=100)
    assert len(jobs) == 1
    assert jobs[0].payload["task"] == "distill"
    assert jobs[0].org_id == "o1"
    await q.ack("jobs", "workers", jobs[0].id)
    assert await q.depth("jobs") == 0


async def test_idempotent_enqueue_dedupes() -> None:
    q = StreamQueue(await _client())
    first = await q.enqueue("jobs", {"x": 1}, idempotency_key="abc")
    second = await q.enqueue("jobs", {"x": 1}, idempotency_key="abc")
    assert first is not None
    assert second is None


async def test_failure_retries_then_dead_letters() -> None:
    q = StreamQueue(await _client(), max_attempts=2)
    await q.ensure_group("jobs", "workers")
    await q.enqueue("jobs", {"x": 1})
    # First failure -> retried (attempts 0 -> 1).
    jobs = await q.read("jobs", "workers", "c1", block_ms=100)
    outcome = await q.fail("jobs", "workers", jobs[0], error="boom")
    assert outcome == "retried"
    # Second failure -> dead-lettered (attempts 1 -> 2 == max).
    jobs = await q.read("jobs", "workers", "c1", block_ms=100)
    outcome = await q.fail("jobs", "workers", jobs[0], error="boom again")
    assert outcome == "dead_lettered"
    assert await q.dlq_depth("jobs") == 1


async def test_quota_enforced() -> None:
    qm = QuotaManager(await _client(), limits={"embed_calls": 3})
    org = uuid.uuid4()
    for _ in range(3):
        await qm.consume(org, "embed_calls")
    with pytest.raises(QuotaExceeded):
        await qm.consume(org, "embed_calls")
    assert await qm.usage(org, "embed_calls") == 4
