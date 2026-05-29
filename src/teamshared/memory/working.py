"""Redis-backed working memory: short-lived per-session conversation buffer.

Data model::

    working:session:{session_id}                 (hash) metadata: agent, topic, opened_at, closed_at
    working:session:{session_id}:turns           (list) JSON-encoded turn dicts in order
    working:agent:{agent}:sessions               (zset, score = opened_at epoch)

Sessions auto-expire via Redis TTL. ``close()`` emits a queue entry for the
distillation worker (``working:distill:queue``).
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord

log = get_logger(__name__)

DISTILL_QUEUE_KEY = "working:distill:queue"
DISTILL_DEAD_LETTER_KEY = "working:distill:dead"
MAX_DISTILL_ATTEMPTS = 3


def _session_key(session_id: str) -> str:
    return f"working:session:{session_id}"


def _turns_key(session_id: str) -> str:
    return f"working:session:{session_id}:turns"


def _agent_index_key(agent: str) -> str:
    return f"working:agent:{agent}:sessions"


class WorkingMemory:
    """Async Redis client wrapper for the working-memory pillar."""

    def __init__(self, url: str, default_ttl: int) -> None:
        self._url = url
        self._default_ttl = default_ttl
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)
            await self._client.ping()
            log.info("working_memory_connected", url=self._url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("WorkingMemory not connected; call connect() first")
        return self._client

    async def open_session(
        self,
        agent: str,
        topic: str | None = None,
        ttl: int | None = None,
    ) -> str:
        """Create a new session and return its id."""
        session_id = "sess_" + secrets.token_urlsafe(12)
        ttl = ttl or self._default_ttl
        now = datetime.now(UTC).isoformat()
        meta = {
            "agent": agent,
            "topic": topic or "",
            "opened_at": now,
            "closed_at": "",
            "ttl": str(ttl),
        }
        pipe = self.client.pipeline()
        pipe.hset(_session_key(session_id), mapping=meta)
        pipe.expire(_session_key(session_id), ttl)
        pipe.expire(_turns_key(session_id), ttl)
        pipe.zadd(
            _agent_index_key(agent),
            {session_id: datetime.now(UTC).timestamp()},
        )
        pipe.expire(_agent_index_key(agent), ttl)
        await pipe.execute()
        log.info("session_opened", session_id=session_id, agent=agent, topic=topic)
        return session_id

    async def append_turn(self, session_id: str, role: str, content: str) -> int:
        """Append a turn and return the new total turn count."""
        await self._require_open(session_id)
        turn = {
            "role": role,
            "content": content,
            "ts": datetime.now(UTC).isoformat(),
        }
        await self.client.rpush(_turns_key(session_id), json.dumps(turn))
        return int(await self.client.llen(_turns_key(session_id)))

    async def get_turns(self, session_id: str) -> list[dict[str, Any]]:
        raw = await self.client.lrange(_turns_key(session_id), 0, -1)
        return [json.loads(item) for item in raw]

    async def get_metadata(self, session_id: str) -> dict[str, str]:
        meta = await self.client.hgetall(_session_key(session_id))
        if not meta:
            raise KeyError(f"unknown session: {session_id}")
        return meta

    async def close_session(self, session_id: str, *, distill: bool = True) -> dict[str, Any]:
        """Mark session closed and (optionally) enqueue for distillation."""
        meta = await self.get_metadata(session_id)
        turns = await self.get_turns(session_id)
        now = datetime.now(UTC).isoformat()
        await self.client.hset(_session_key(session_id), "closed_at", now)

        if distill:
            job = json.dumps(
                {
                    "session_id": session_id,
                    "agent": meta.get("agent"),
                    "topic": meta.get("topic") or None,
                    "opened_at": meta.get("opened_at"),
                    "closed_at": now,
                    "turn_count": len(turns),
                }
            )
            await self.client.rpush(DISTILL_QUEUE_KEY, job)
            log.info("session_enqueued_for_distill", session_id=session_id, turns=len(turns))

        return {
            "session_id": session_id,
            "turn_count": len(turns),
            "closed_at": now,
            "distill_enqueued": distill,
        }

    async def stats(self, recent_limit: int = 20) -> dict[str, Any]:
        """Aggregate working-memory stats across all agents.

        Scans every ``working:session:*`` hash (skipping the ``:turns`` lists),
        splitting active (``closed_at == ""``) from closed sessions and grouping
        by agent. Also reports distill-queue depths and the most recent sessions
        with their turn counts. Used by the public ``/memory`` dashboard.
        """
        client = self.client
        sessions: list[dict[str, Any]] = []
        async for key in client.scan_iter(match="working:session:*", count=200):
            if key.endswith(":turns"):
                continue
            meta = await client.hgetall(key)
            if not meta:
                continue
            session_id = key.split("working:session:", 1)[1]
            sessions.append({"session_id": session_id, **meta})

        active = 0
        closed = 0
        by_agent: dict[str, int] = {}
        for s in sessions:
            agent = s.get("agent") or "unknown"
            by_agent[agent] = by_agent.get(agent, 0) + 1
            if s.get("closed_at"):
                closed += 1
            else:
                active += 1

        sessions.sort(key=lambda s: s.get("opened_at") or "", reverse=True)
        recent: list[dict[str, Any]] = []
        for s in sessions[:recent_limit]:
            turn_count = int(await client.llen(_turns_key(s["session_id"])))
            recent.append({**s, "turn_count": turn_count})

        return {
            "total": len(sessions),
            "active": active,
            "closed": closed,
            "by_agent": by_agent,
            "distill_queue": int(await client.llen(DISTILL_QUEUE_KEY)),
            "distill_dead": int(await client.llen(DISTILL_DEAD_LETTER_KEY)),
            "recent": recent,
        }

    async def list_open_sessions(self, agent: str, limit: int = 20) -> list[dict[str, Any]]:
        ids = await self.client.zrevrange(_agent_index_key(agent), 0, limit - 1)
        out: list[dict[str, Any]] = []
        for sid in ids:
            meta = await self.client.hgetall(_session_key(sid))
            if meta:
                out.append({"session_id": sid, **meta})
        return out

    async def recent_records(self, agent: str, k: int = 5) -> list[MemoryRecord]:
        """Return the last ``k`` turns across the agent's most recent open session.

        Used by the unified recall path so working memory contributes context.
        """
        sessions = await self.list_open_sessions(agent, limit=1)
        if not sessions:
            return []
        session_id = sessions[0]["session_id"]
        turns = await self.get_turns(session_id)
        out: list[MemoryRecord] = []
        for turn in turns[-k:]:
            out.append(
                MemoryRecord(
                    id=f"{session_id}:{turn['ts']}",
                    pillar="working",
                    content=f"[{turn['role']}] {turn['content']}",
                    agent=agent,
                    metadata={"session_id": session_id, "ts": turn["ts"]},
                )
            )
        return out

    async def pop_distill_job(self, timeout: int = 5) -> dict[str, Any] | None:
        """Blocking-pop the next distillation job. Returns None on timeout."""
        result = await self.client.blpop([DISTILL_QUEUE_KEY], timeout=timeout)
        if result is None:
            return None
        _, payload = result
        return json.loads(payload)

    async def requeue_distill_job(self, job: dict[str, Any]) -> None:
        """Retry a failed distillation job or move it to the dead-letter queue."""
        attempts = int(job.get("attempts", 0)) + 1
        job["attempts"] = attempts
        payload = json.dumps(job)
        if attempts >= MAX_DISTILL_ATTEMPTS:
            await self.client.rpush(DISTILL_DEAD_LETTER_KEY, payload)
            log.error(
                "distill_job_dead_letter",
                session_id=job.get("session_id"),
                attempts=attempts,
            )
            return
        await self.client.rpush(DISTILL_QUEUE_KEY, payload)
        log.warning(
            "distill_job_requeued",
            session_id=job.get("session_id"),
            attempts=attempts,
        )

    async def _require_open(self, session_id: str) -> None:
        meta = await self.client.hgetall(_session_key(session_id))
        if not meta:
            raise KeyError(f"unknown session: {session_id}")
        if meta.get("closed_at"):
            raise ValueError(f"session {session_id} is closed")
