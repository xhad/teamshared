"""Queue observability and capture metrics (Stage 4.3)."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from teamshared.config import Settings
from teamshared.memory.working import (
    CURATE_QUEUE_KEY,
    DISTILL_DEAD_LETTER_KEY,
    DISTILL_QUEUE_KEY,
    WorkingMemory,
)
from teamshared.metrics import METRICS
from teamshared.observability.queues import (
    QueueStats,
    evaluate_queue_alerts,
    fetch_queue_stats,
    queues_degraded,
    refresh_queue_metrics,
)


@pytest.fixture
def working() -> WorkingMemory:
    wm = WorkingMemory("redis://unused", default_ttl=3600)
    wm._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return wm


@pytest.mark.asyncio
async def test_queue_stats_and_metrics(working: WorkingMemory) -> None:
    await working.client.rpush(DISTILL_QUEUE_KEY, "job1", "job2")
    await working.client.rpush(DISTILL_DEAD_LETTER_KEY, "dead1")
    await working.client.rpush(CURATE_QUEUE_KEY, "c1")
    stats = await refresh_queue_metrics(working)
    assert stats.distill_queue == 2
    assert stats.distill_dead == 1
    assert stats.curate_queue == 1
    out = METRICS.render()
    assert 'teamshared_queue_depth{stream="distill"} 2' in out
    assert 'teamshared_queue_dead_letter_depth{stream="distill"} 1' in out


@pytest.mark.asyncio
async def test_evaluate_queue_alerts_critical_on_dead_letter() -> None:
    settings = Settings(_env_file=None, queue_depth_warn_threshold=10)
    stats = QueueStats(
        distill_queue=0, distill_dead=1, curate_queue=0, curate_dead=0, curate_pending=0
    )
    alerts = evaluate_queue_alerts(stats, settings)
    assert any(a["code"] == "distill_dead_letter" and a["severity"] == "critical" for a in alerts)
    assert queues_degraded(alerts)


@pytest.mark.asyncio
async def test_evaluate_queue_alerts_warn_on_depth() -> None:
    settings = Settings(
        _env_file=None,
        queue_depth_warn_threshold=5,
        queue_depth_critical_threshold=20,
    )
    stats = QueueStats(
        distill_queue=7, distill_dead=0, curate_queue=0, curate_dead=0, curate_pending=0
    )
    alerts = evaluate_queue_alerts(stats, settings)
    assert any(a["severity"] == "warning" for a in alerts)
    assert not queues_degraded(alerts)


@pytest.mark.asyncio
async def test_fetch_queue_stats(working: WorkingMemory) -> None:
    await working.client.rpush(DISTILL_QUEUE_KEY, "x")
    raw = await fetch_queue_stats(working)
    assert raw.distill_queue == 1
