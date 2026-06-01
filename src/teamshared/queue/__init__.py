"""Durable background work on Redis Streams.

Replaces the at-most-once ``BLPOP`` loop with consumer groups (so multiple
workers share a stream without dropping jobs), retries with exponential
backoff, a dead-letter stream for poison jobs, and producer-side idempotency.
Per-org quotas provide backpressure so one tenant cannot exhaust shared
capacity (notably embedding spend).
"""

from teamshared.queue.quotas import QuotaExceeded, QuotaManager
from teamshared.queue.streams import Job, StreamQueue

__all__ = ["Job", "QuotaExceeded", "QuotaManager", "StreamQueue"]
