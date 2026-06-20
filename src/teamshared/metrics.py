"""Tiny, dependency-free Prometheus-style metrics registry.

Avoids a hard ``prometheus_client`` dependency while still exposing the
text exposition format at ``/metrics``. Supports counters, gauges, and simple
fixed-bucket histograms with labels. Thread-safety is sufficient for the
asyncio single-loop server; swap in ``prometheus_client`` if multiprocess
scraping is needed.

Key SLO signals: retrieval latency, embedding spend, queue depth,
permission-denied rate, and the cross-tenant-violation counter (which should
always be zero -- any increment pages on-call).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


def _fmt_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"


@dataclass
class _Counter:
    name: str
    help: str
    values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _label_key(labels)
        self.values[key] = self.values.get(key, 0.0) + amount

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        if not self.values:
            out.append(f"{self.name} 0")
        for key, val in self.values.items():
            out.append(f"{self.name}{_fmt_labels(key)} {val}")
        return out


@dataclass
class _Gauge:
    name: str
    help: str
    values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)

    def set(self, value: float, **labels: str) -> None:
        self.values[_label_key(labels)] = value

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        for key, val in self.values.items():
            out.append(f"{self.name}{_fmt_labels(key)} {val}")
        return out


@dataclass
class _Histogram:
    name: str
    help: str
    buckets: tuple[float, ...] = _LATENCY_BUCKETS
    counts: dict[tuple[tuple[str, str], ...], list[int]] = field(default_factory=dict)
    sums: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)

    def observe(self, value: float, **labels: str) -> None:
        key = _label_key(labels)
        counts = self.counts.setdefault(key, [0] * (len(self.buckets) + 1))
        self.sums[key] = self.sums.get(key, 0.0) + value
        placed = False
        for i, edge in enumerate(self.buckets):
            if value <= edge:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key, counts in self.counts.items():
            cumulative = 0
            base = _fmt_labels(key)[:-1] if key else "{"
            for i, edge in enumerate(self.buckets):
                cumulative += counts[i]
                sep = "," if key else ""
                out.append(f'{self.name}_bucket{base}{sep}le="{edge}"}} {cumulative}')
            cumulative += counts[-1]
            sep = "," if key else ""
            out.append(f'{self.name}_bucket{base}{sep}le="+Inf"}} {cumulative}')
            out.append(f"{self.name}_sum{_fmt_labels(key)} {self.sums.get(key, 0.0)}")
            out.append(f"{self.name}_count{_fmt_labels(key)} {cumulative}")
        return out


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.retrieval_latency = _Histogram(
            "teamshared_retrieval_latency_seconds", "Memory retrieval latency"
        )
        self.embed_calls = _Counter("teamshared_embed_calls_total", "Embedding API calls")
        self.embed_texts = _Counter("teamshared_embed_texts_total", "Texts embedded")
        self.queue_depth = _Gauge("teamshared_queue_depth", "Pending jobs per stream")
        self.queue_dead_letter = _Gauge(
            "teamshared_queue_dead_letter_depth",
            "Jobs in dead-letter queues",
        )
        self.queue_pending = _Gauge(
            "teamshared_queue_pending_depth",
            "Subjects awaiting curation (debounce set size)",
        )
        self.capture_recorded = _Counter(
            "teamshared_capture_recorded_total",
            "Conversation turns recorded",
        )
        self.permission_denied = _Counter(
            "teamshared_permission_denied_total", "Permission checks denied"
        )
        self.cross_tenant_violation = _Counter(
            "teamshared_cross_tenant_violation_total",
            "Out-of-scope rows dropped post-retrieval (should always be 0)",
        )
        self.memory_writes = _Counter("teamshared_memory_writes_total", "Memory items written")
        self.auth_rejected = _Counter(
            "teamshared_auth_rejected_total", "Bearer auth rejections at the HTTP edge"
        )
        self.otp_failed = _Counter(
            "teamshared_otp_failed_total", "Console OTP verification failures"
        )
        self.ingestion_quarantined = _Counter(
            "teamshared_ingestion_quarantined_total",
            "Memory writes quarantined or sent to approval by ingestion",
        )
        self.rate_limited = _Counter(
            "teamshared_rate_limited_total", "HTTP requests rejected by edge rate limits"
        )
        self.job_signature_invalid = _Counter(
            "teamshared_job_signature_invalid_total",
            "Distill/curate queue jobs rejected due to missing or invalid HMAC",
        )
        self.admin_export_total = _Counter(
            "teamshared_admin_export_total",
            "Org memory exports (API or console)",
        )
        self.admin_purge_total = _Counter(
            "teamshared_admin_purge_total",
            "Per-user memory erasure operations",
        )
        self.context_pack_built = _Counter(
            "teamshared_context_pack_built_total",
            "Context packs assembled via memory_assemble_context",
        )
        self.context_pack_tokens = _Histogram(
            "teamshared_context_pack_tokens",
            "Estimated tokens used per assembled context pack",
            buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000),
        )
        self.agent_runs_started = _Counter(
            "teamshared_agent_runs_started_total", "Background agent runs started"
        )
        self.agent_runs_completed = _Counter(
            "teamshared_agent_runs_completed_total", "Background agent runs completed"
        )
        self.agent_runs_failed = _Counter(
            "teamshared_agent_runs_failed_total", "Background agent runs failed"
        )
        self.agent_runs_cancelled = _Counter(
            "teamshared_agent_runs_cancelled_total", "Background agent runs cancelled"
        )
        self.agent_run_latency = _Histogram(
            "teamshared_agent_run_model_latency_seconds",
            "Background agent run model-call latency",
        )
        self.compress_requests = _Counter(
            "teamshared_compress_requests_total",
            "Prompt payloads compressed before LLM calls",
        )
        self.compress_chars_saved = _Counter(
            "teamshared_compress_chars_saved_total",
            "Characters removed by context compression",
        )

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            for metric in (
                self.retrieval_latency, self.embed_calls, self.embed_texts,
                self.queue_depth, self.queue_dead_letter, self.queue_pending,
                self.capture_recorded, self.permission_denied,
                self.cross_tenant_violation, self.memory_writes, self.auth_rejected,
                self.otp_failed, self.ingestion_quarantined,
                self.rate_limited, self.job_signature_invalid,
                self.admin_export_total, self.admin_purge_total,
                self.context_pack_built, self.context_pack_tokens,
                self.agent_runs_started, self.agent_runs_completed,
                self.agent_runs_failed, self.agent_runs_cancelled,
                self.agent_run_latency,
                self.compress_requests, self.compress_chars_saved,
            ):
                lines.extend(metric.render())
            return "\n".join(lines) + "\n"


METRICS = Metrics()
