"""Redis distill/curate queue gauges and alert evaluation (Stage 4.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from teamshared.config import Settings
from teamshared.logging import get_logger
from teamshared.memory.working import WorkingMemory
from teamshared.metrics import METRICS

log = get_logger(__name__)


@dataclass(frozen=True)
class QueueStats:
    distill_queue: int
    distill_dead: int
    curate_queue: int
    curate_dead: int
    curate_pending: int

    def as_dict(self) -> dict[str, int]:
        return {
            "distill_queue": self.distill_queue,
            "distill_dead": self.distill_dead,
            "curate_queue": self.curate_queue,
            "curate_dead": self.curate_dead,
            "curate_pending": self.curate_pending,
        }


async def fetch_queue_stats(working: WorkingMemory) -> QueueStats:
    raw = await working.queue_stats()
    return QueueStats(
        distill_queue=int(raw["distill_queue"]),
        distill_dead=int(raw["distill_dead"]),
        curate_queue=int(raw["curate_queue"]),
        curate_dead=int(raw["curate_dead"]),
        curate_pending=int(raw["curate_pending"]),
    )


async def refresh_queue_metrics(working: WorkingMemory) -> QueueStats:
    """Publish queue depths to Prometheus gauges."""
    stats = await fetch_queue_stats(working)
    METRICS.queue_depth.set(stats.distill_queue, stream="distill")
    METRICS.queue_depth.set(stats.curate_queue, stream="curate")
    METRICS.queue_dead_letter.set(stats.distill_dead, stream="distill")
    METRICS.queue_dead_letter.set(stats.curate_dead, stream="curate")
    METRICS.queue_pending.set(stats.curate_pending, stream="curate")
    return stats


def evaluate_queue_alerts(stats: QueueStats, settings: Settings) -> list[dict[str, Any]]:
    """Return human-readable alert records for health dashboards and logs."""
    warn_at = int(getattr(settings, "queue_depth_warn_threshold", 100))
    critical_at = int(getattr(settings, "queue_depth_critical_threshold", 500))
    alerts: list[dict[str, Any]] = []
    if stats.distill_dead > 0:
        alerts.append({
            "code": "distill_dead_letter",
            "severity": "critical",
            "message": f"{stats.distill_dead} distillation job(s) in dead-letter queue",
        })
    if stats.curate_dead > 0:
        alerts.append({
            "code": "curate_dead_letter",
            "severity": "critical",
            "message": f"{stats.curate_dead} curation job(s) in dead-letter queue",
        })
    if stats.distill_queue >= critical_at:
        alerts.append({
            "code": "distill_queue_depth",
            "severity": "critical",
            "message": (
                f"distill queue depth {stats.distill_queue} "
                f">= critical threshold {critical_at}"
            ),
        })
    elif stats.distill_queue >= warn_at:
        alerts.append({
            "code": "distill_queue_depth",
            "severity": "warning",
            "message": (
                f"distill queue depth {stats.distill_queue} "
                f">= warn threshold {warn_at}"
            ),
        })
    if stats.curate_queue >= critical_at:
        alerts.append({
            "code": "curate_queue_depth",
            "severity": "critical",
            "message": (
                f"curate queue depth {stats.curate_queue} "
                f">= critical threshold {critical_at}"
            ),
        })
    elif stats.curate_queue >= warn_at:
        alerts.append({
            "code": "curate_queue_depth",
            "severity": "warning",
            "message": (
                f"curate queue depth {stats.curate_queue} "
                f">= warn threshold {warn_at}"
            ),
        })
    return alerts


def queues_degraded(alerts: list[dict[str, Any]]) -> bool:
    return any(a.get("severity") == "critical" for a in alerts)
