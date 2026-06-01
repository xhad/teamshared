"""Redis-backed working memory: short-lived per-session conversation buffer.

Every key is namespaced by ``org_id`` so the working pillar is tenant-isolated
just like the durable pillars (G2). Data model::

    working:{org}:session:{session_id}            (hash) metadata: org_id, agent, topic, opened_at, closed_at
    working:{org}:session:{session_id}:turns      (list) JSON-encoded turn dicts in order
    working:{org}:agent:{agent}:sessions          (zset, score = opened_at epoch)
    working:{org}:agent:{agent}:autosession       (string) rolling capture pointer

Sessions auto-expire via Redis TTL. ``close()`` emits a queue entry for the
distillation worker (``working:distill:queue``, global; the job payload carries
``org_id``).
"""

from __future__ import annotations

import contextlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord

log = get_logger(__name__)

DISTILL_QUEUE_KEY = "working:distill:queue"
DISTILL_DEAD_LETTER_KEY = "working:distill:dead"
MAX_DISTILL_ATTEMPTS = 3

# Topic stamped on sessions assembled implicitly by the tool-call capture
# middleware (see ``teamshared.server.capture``), as opposed to sessions an
# agent opens explicitly via ``memory_session_open``.
AUTO_CAPTURE_TOPIC = "auto-capture"


def _org(org_id: UUID | str) -> str:
    return str(org_id)


def _session_key(org_id: UUID | str, session_id: str) -> str:
    return f"working:{_org(org_id)}:session:{session_id}"


def _turns_key(org_id: UUID | str, session_id: str) -> str:
    return f"working:{_org(org_id)}:session:{session_id}:turns"


def _agent_index_key(org_id: UUID | str, agent: str) -> str:
    return f"working:{_org(org_id)}:agent:{agent}:sessions"


def _auto_session_key(org_id: UUID | str, agent: str) -> str:
    return f"working:{_org(org_id)}:agent:{agent}:autosession"


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
        org_id: UUID | str,
        agent: str,
        topic: str | None = None,
        ttl: int | None = None,
    ) -> str:
        """Create a new session and return its id."""
        session_id = "sess_" + secrets.token_urlsafe(12)
        ttl = ttl or self._default_ttl
        now = datetime.now(UTC).isoformat()
        meta = {
            "org_id": _org(org_id),
            "agent": agent,
            "topic": topic or "",
            "opened_at": now,
            "closed_at": "",
            "ttl": str(ttl),
        }
        pipe = self.client.pipeline()
        pipe.hset(_session_key(org_id, session_id), mapping=meta)
        pipe.expire(_session_key(org_id, session_id), ttl)
        pipe.expire(_turns_key(org_id, session_id), ttl)
        pipe.zadd(
            _agent_index_key(org_id, agent),
            {session_id: datetime.now(UTC).timestamp()},
        )
        pipe.expire(_agent_index_key(org_id, agent), ttl)
        await pipe.execute()
        log.info("session_opened", session_id=session_id, org_id=_org(org_id), agent=agent, topic=topic)
        return session_id

    async def append_turn(self, org_id: UUID | str, session_id: str, role: str, content: str) -> int:
        """Append a turn and return the new total turn count."""
        await self._require_open(org_id, session_id)
        turn = {
            "role": role,
            "content": content,
            "ts": datetime.now(UTC).isoformat(),
        }
        await self.client.rpush(_turns_key(org_id, session_id), json.dumps(turn))
        return int(await self.client.llen(_turns_key(org_id, session_id)))

    async def get_turns(self, org_id: UUID | str, session_id: str) -> list[dict[str, Any]]:
        raw = await self.client.lrange(_turns_key(org_id, session_id), 0, -1)
        return [json.loads(item) for item in raw]

    async def get_metadata(self, org_id: UUID | str, session_id: str) -> dict[str, str]:
        meta = await self.client.hgetall(_session_key(org_id, session_id))
        if not meta:
            raise KeyError(f"unknown session: {session_id}")
        return meta

    async def close_session(
        self, org_id: UUID | str, session_id: str, *, distill: bool = True
    ) -> dict[str, Any]:
        """Mark session closed and (optionally) enqueue for distillation."""
        meta = await self.get_metadata(org_id, session_id)
        turns = await self.get_turns(org_id, session_id)
        now = datetime.now(UTC).isoformat()
        await self.client.hset(_session_key(org_id, session_id), "closed_at", now)

        if distill:
            job = json.dumps(
                {
                    "org_id": _org(org_id),
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

    async def record_turn(
        self,
        org_id: UUID | str,
        agent: str,
        role: str,
        content: str,
        *,
        idle_seconds: int,
        max_turns: int,
    ) -> str:
        """Append one ``role``/``content`` turn to the agent's auto-capture session.

        This is the harness-agnostic capture path. Two producers feed it:
        the tool-call middleware (``role="tool"``) and the conversation
        ingestion endpoint (``role="user"`` / ``"assistant"``), so a single
        rolling session per agent holds the interleaved story. The session
        rolls over — close (with distillation enqueued) plus open a fresh one —
        when it has been idle longer than ``idle_seconds`` or has accumulated
        ``max_turns`` turns. The previous session id, its last activity
        timestamp, and its turn count are tracked in a small pointer key so we
        don't have to scan Redis on every call.
        """
        now = datetime.now(UTC).timestamp()
        pointer_key = _auto_session_key(org_id, agent)
        raw = await self.client.get(pointer_key)

        session_id: str | None = None
        if raw:
            try:
                pointer = json.loads(raw)
            except (TypeError, ValueError):
                pointer = {}
            existing = pointer.get("session_id")
            last_activity = float(pointer.get("last_activity", 0) or 0)
            turns = int(pointer.get("turns", 0) or 0)
            fresh = (now - last_activity) < idle_seconds and turns < max_turns
            if existing and fresh:
                session_id = existing
            elif existing:
                with contextlib.suppress(KeyError):
                    await self.close_session(org_id, existing, distill=True)

        if session_id is None:
            session_id = await self.open_session(org_id, agent, topic=AUTO_CAPTURE_TOPIC)

        try:
            turn_count = await self.append_turn(org_id, session_id, role, content)
        except (KeyError, ValueError):
            # Session expired or was closed out from under us; start a new one.
            session_id = await self.open_session(org_id, agent, topic=AUTO_CAPTURE_TOPIC)
            turn_count = await self.append_turn(org_id, session_id, role, content)

        pointer_payload = json.dumps(
            {"session_id": session_id, "last_activity": now, "turns": turn_count}
        )
        await self.client.set(pointer_key, pointer_payload)
        await self.client.expire(pointer_key, self._default_ttl)
        return session_id

    async def record_tool_call(
        self,
        org_id: UUID | str,
        agent: str,
        content: str,
        *,
        idle_seconds: int,
        max_turns: int,
    ) -> str:
        """Record a tool call as a ``tool`` turn (thin wrapper over record_turn)."""
        return await self.record_turn(
            org_id, agent, "tool", content, idle_seconds=idle_seconds, max_turns=max_turns
        )

    async def stats(self, org_id: UUID | str, recent_limit: int = 20) -> dict[str, Any]:
        """Aggregate working-memory stats for one org.

        Scans every ``working:{org}:session:*`` hash (skipping the ``:turns``
        lists), splitting active (``closed_at == ""``) from closed sessions and
        grouping by agent. Also reports distill-queue depths and the most recent
        sessions with their turn counts. Used by the ``/memory`` dashboard.
        """
        client = self.client
        prefix = f"working:{_org(org_id)}:session:"
        sessions: list[dict[str, Any]] = []
        async for key in client.scan_iter(match=f"{prefix}*", count=200):
            if key.endswith(":turns"):
                continue
            meta = await client.hgetall(key)
            if not meta:
                continue
            session_id = key.split(prefix, 1)[1]
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
            turn_count = int(await client.llen(_turns_key(org_id, s["session_id"])))
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

    async def list_open_sessions(
        self, org_id: UUID | str, agent: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        ids = await self.client.zrevrange(_agent_index_key(org_id, agent), 0, limit - 1)
        out: list[dict[str, Any]] = []
        for sid in ids:
            meta = await self.client.hgetall(_session_key(org_id, sid))
            if meta:
                out.append({"session_id": sid, **meta})
        return out

    async def recent_records(self, org_id: UUID | str, agent: str, k: int = 5) -> list[MemoryRecord]:
        """Return the last ``k`` turns across the agent's most recent open session.

        Used by the unified recall path so working memory contributes context.
        """
        sessions = await self.list_open_sessions(org_id, agent, limit=1)
        if not sessions:
            return []
        session_id = sessions[0]["session_id"]
        turns = await self.get_turns(org_id, session_id)
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

    async def _require_open(self, org_id: UUID | str, session_id: str) -> None:
        meta = await self.client.hgetall(_session_key(org_id, session_id))
        if not meta:
            raise KeyError(f"unknown session: {session_id}")
        if meta.get("closed_at"):
            raise ValueError(f"session {session_id} is closed")
