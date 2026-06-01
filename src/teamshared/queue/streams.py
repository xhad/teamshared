"""Redis Streams job queue with consumer groups, backoff retries, and a DLQ.

Every job carries its ``org_id`` and a trace id so workers can re-establish the
tenant context and correlate with traces. Producer idempotency is enforced with
a ``SET NX`` guard keyed on a caller-supplied idempotency key.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as redis

from teamshared.logging import get_logger

log = get_logger(__name__)

_MAX_ATTEMPTS = 5
_BASE_BACKOFF_MS = 500


@dataclass
class Job:
    id: str
    stream: str
    payload: dict[str, Any]
    attempts: int = 0
    org_id: str | None = None
    trace_id: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


class StreamQueue:
    def __init__(self, client: redis.Redis, *, max_attempts: int = _MAX_ATTEMPTS) -> None:
        self.client = client
        self.max_attempts = max_attempts

    def _dlq(self, stream: str) -> str:
        return f"{stream}:dlq"

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self.client.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(
        self,
        stream: str,
        payload: dict[str, Any],
        *,
        org_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        attempts: int = 0,
    ) -> str | None:
        """Add a job. Returns the stream id, or ``None`` if deduped by idempotency."""
        if idempotency_key is not None:
            ok = await self.client.set(
                f"qidem:{stream}:{idempotency_key}", "1", nx=True, ex=86400
            )
            if not ok:
                log.info("queue_idempotent_skip", stream=stream, key=idempotency_key)
                return None
        fields: dict[str, str] = {
            "payload": json.dumps(payload),
            "attempts": str(attempts),
            "org_id": org_id or "",
            "trace_id": trace_id or "",
            "enqueued_at": str(time.time()),
        }
        msg_id = await self.client.xadd(stream, fields)  # type: ignore[arg-type]
        return msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

    async def read(
        self, stream: str, group: str, consumer: str, *, count: int = 10, block_ms: int = 5000
    ) -> list[Job]:
        resp = await self.client.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        jobs: list[Job] = []
        for _stream, messages in resp or []:
            for msg_id, raw in messages:
                jobs.append(_to_job(stream, msg_id, raw))
        return jobs

    async def ack(self, stream: str, group: str, job_id: str) -> None:
        await self.client.xack(stream, group, job_id)
        await self.client.xdel(stream, job_id)

    async def fail(self, stream: str, group: str, job: Job, *, error: str) -> str:
        """Either re-enqueue with backoff or DLQ, then ack+remove the original.

        The replacement entry is written *before* the original is deleted so its
        stream id is strictly greater than the failed one (and so an empty
        stream can never recycle an id back onto a consumer group's cursor).
        """
        next_attempts = job.attempts + 1
        if next_attempts >= self.max_attempts:
            await self.client.xadd(
                self._dlq(stream),
                {
                    "payload": json.dumps(job.payload),
                    "attempts": str(next_attempts),
                    "org_id": job.org_id or "",
                    "trace_id": job.trace_id or "",
                    "error": error[:500],
                },
            )
            outcome = "dead_lettered"
            log.warning("queue_dead_lettered", stream=stream, attempts=next_attempts, error=error)
        else:
            # Exponential backoff is advisory metadata a worker can honor before
            # reprocessing; the job is re-added for this single-stream design.
            backoff_ms = _BASE_BACKOFF_MS * (2**job.attempts)
            await self.enqueue(
                stream, job.payload, org_id=job.org_id, trace_id=job.trace_id,
                attempts=next_attempts,
            )
            outcome = "retried"
            log.info("queue_retry", stream=stream, attempts=next_attempts, backoff_ms=backoff_ms)

        await self.client.xack(stream, group, job.id)
        await self.client.xdel(stream, job.id)
        return outcome

    async def depth(self, stream: str) -> int:
        return int(await self.client.xlen(stream))

    async def dlq_depth(self, stream: str) -> int:
        try:
            return int(await self.client.xlen(self._dlq(stream)))
        except redis.ResponseError:
            return 0


def _to_job(stream: str, msg_id: Any, raw: dict[Any, Any]) -> Job:
    def _g(key: str, default: str = "") -> str:
        for k, v in raw.items():
            kk = k.decode() if isinstance(k, bytes) else k
            if kk == key:
                return v.decode() if isinstance(v, bytes) else v
        return default

    payload_raw = _g("payload", "{}")
    job_id = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
    return Job(
        id=job_id,
        stream=stream,
        payload=json.loads(payload_raw),
        attempts=int(_g("attempts", "0")),
        org_id=_g("org_id") or None,
        trace_id=_g("trace_id") or None,
    )
