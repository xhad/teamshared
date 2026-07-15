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
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import redis.asyncio as redis

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord
from teamshared.metrics import METRICS
from teamshared.queue.job_sign import JobSignError, decode_job, encode_job, peek_job

log = get_logger(__name__)

DISTILL_QUEUE_KEY = "working:distill:queue"
DISTILL_DEAD_LETTER_KEY = "working:distill:dead"
MAX_DISTILL_ATTEMPTS = 3

# Curation queue: subjects whose wiki page needs (re)synthesis. A subject is
# enqueued once it accumulates CURATE_THRESHOLD new facts (debounce), and a
# pending set keeps a busy subject from being queued repeatedly before the
# CuratorWorker drains it.
CURATE_QUEUE_KEY = "working:curate:queue"
CURATE_DEAD_LETTER_KEY = "working:curate:dead"
# Dead-letter lists keep only the newest N failed jobs (bounded growth).
DEAD_LETTER_MAX_LEN = 1000
CURATE_PENDING_KEY = "working:curate:pending"
MAX_CURATE_ATTEMPTS = 3


def _curate_count_key(org_id: UUID | str, subject: str) -> str:
    return f"working:{_org(org_id)}:curate:count:{subject}"

# Console sign-in one-time passcodes (OTP). Stored hashed under a short TTL,
# keyed by email, single-use, with a wrong-attempt cap.
_OTP_PREFIX = "auth:otp:login:"

# OAuth state nonces (CSRF protection for the Gmail/Slack OAuth redirect flow).
# Short-TTL, single-use, keyed by the opaque state token. Stores a JSON blob of
# {account_id, org_id, kind, redirect_uri} so the callback can recover context
# without trusting the browser.
_OAUTH_STATE_PREFIX = "auth:oauth:state:"


def _otp_key(email: str) -> str:
    return f"{_OTP_PREFIX}{email.strip().lower()}"


def _oauth_state_key(state: str) -> str:
    return f"{_OAUTH_STATE_PREFIX}{state}"


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


# Liveness heartbeats: a process (e.g. the distill worker) periodically writes a
# short-TTL key so the health probe can tell whether it is still running.
_HEARTBEAT_PREFIX = "working:heartbeat:"

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


def _conversation_key(org_id: UUID | str, agent: str, fingerprint: str) -> str:
    return f"working:{_org(org_id)}:agent:{agent}:conversation:{fingerprint}"


def _redis_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _normalize_hash(meta: dict[str | bytes, str | bytes]) -> dict[str, str]:
    return {_redis_text(k): _redis_text(v) for k, v in meta.items()}


class WorkingMemory:
    """Async Redis client wrapper for the working-memory pillar."""

    def __init__(
        self,
        url: str,
        default_ttl: int,
        *,
        job_signing_secret: str | None = None,
    ) -> None:
        self._url = url
        self._default_ttl = default_ttl
        self._job_signing_secret = job_signing_secret
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

    # --- console sign-in OTP --------------------------------------------

    async def set_login_otp(
        self,
        email: str,
        code: str,
        *,
        ttl: int = 30,
        max_attempts: int = 5,
    ) -> None:
        """Store a hashed, short-lived sign-in code for ``email`` (single-use).

        Email-only: the code proves ownership of an email address, and the
        console resolves which org(s) that email belongs to *after* verifying.
        Overwrites any prior code for the same email, so requesting a new code
        invalidates the old one.
        """
        key = _otp_key(email)
        pipe = self.client.pipeline()
        pipe.delete(key)
        pipe.hset(
            key,
            mapping={
                "hash": _hash_otp(code),
                "attempts": "0",
                "max": str(max_attempts),
            },
        )
        pipe.expire(key, ttl)
        await pipe.execute()

    async def verify_login_otp(self, email: str, code: str) -> bool:
        """Check a sign-in code for ``email``. Returns ``True`` on success.

        Codes are single-use (consumed on success) and capped at ``max``
        wrong attempts, after which the code is dropped. Expiry is enforced by
        the Redis TTL set in :meth:`set_login_otp`.
        """
        key = _otp_key(email)
        data = _normalize_hash(await self.client.hgetall(key))
        if not data:
            return False
        attempts = int(data.get("attempts", "0"))
        max_attempts = int(data.get("max", "5"))
        if attempts >= max_attempts:
            await self.client.delete(key)
            return False
        if code and hmac.compare_digest(_hash_otp(code), data.get("hash", "")):
            await self.client.delete(key)
            return True
        # Wrong code: burn an attempt but keep the existing TTL.
        await self.client.hincrby(key, "attempts", 1)
        return False

    # --- OAuth state (CSRF nonce for Gmail/Slack redirect flow) -----------

    async def set_oauth_state(self, state: str, payload: dict[str, Any], *, ttl: int = 600) -> None:
        """Store a short-lived, single-use OAuth state nonce.

        ``payload`` carries the context the callback needs to recover
        (account_id, org_id, kind, redirect_uri). Single-use: popped on read.
        """
        await self.client.set(_oauth_state_key(state), json.dumps(payload), ex=ttl)

    async def pop_oauth_state(self, state: str) -> dict[str, Any] | None:
        """Consume and return the OAuth state payload, or None if missing/expired."""
        raw = await self.client.getdel(_oauth_state_key(state))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def open_session(
        self,
        org_id: UUID | str,
        agent: str,
        topic: str | None = None,
        ttl: int | None = None,
        repo: str | None = None,
        github: str | None = None,
    ) -> str:
        """Create a new session and return its id."""
        session_id = "sess_" + secrets.token_urlsafe(12)
        ttl = ttl or self._default_ttl
        now = datetime.now(UTC).isoformat()
        meta = {
            "org_id": _org(org_id),
            "agent": agent,
            "topic": topic or "",
            "repo": repo or "",
            "github": github or "",
            "opened_at": now,
            "closed_at": "",
            "ttl": str(ttl),
        }
        pipe = self.client.pipeline()
        pipe.hset(_session_key(org_id, session_id), mapping=cast("dict[Any, Any]", meta))
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
        """Append a turn and return the new total turn count.

        Refreshes the session TTL so an actively-used session never expires
        mid-conversation (the TTL is a *idle* timeout, not a hard lifetime).
        """
        meta = await self._require_open(org_id, session_id)
        turn = {
            "role": role,
            "content": content,
            "ts": datetime.now(UTC).isoformat(),
        }
        ttl = int(meta.get("ttl") or self._default_ttl)
        pipe = self.client.pipeline()
        pipe.rpush(_turns_key(org_id, session_id), json.dumps(turn))
        pipe.expire(_session_key(org_id, session_id), ttl)
        pipe.expire(_turns_key(org_id, session_id), ttl)
        pipe.llen(_turns_key(org_id, session_id))
        results = await pipe.execute()
        return int(results[-1])

    async def get_turns(self, org_id: UUID | str, session_id: str) -> list[dict[str, Any]]:
        raw = await self.client.lrange(_turns_key(org_id, session_id), 0, -1)
        return [json.loads(item) for item in raw]

    async def get_metadata(self, org_id: UUID | str, session_id: str) -> dict[str, str]:
        meta = await self.client.hgetall(_session_key(org_id, session_id))
        if not meta:
            raise KeyError(f"unknown session: {session_id}")
        return _normalize_hash(meta)

    async def close_session(
        self, org_id: UUID | str, session_id: str, *, distill: bool = True
    ) -> dict[str, Any]:
        """Mark session closed and (optionally) enqueue for distillation."""
        meta = await self.get_metadata(org_id, session_id)
        turns = await self.get_turns(org_id, session_id)
        now = datetime.now(UTC).isoformat()
        await self.client.hset(_session_key(org_id, session_id), "closed_at", now)

        if distill:
            job = {
                "org_id": _org(org_id),
                "session_id": session_id,
                "agent": meta.get("agent"),
                "topic": meta.get("topic") or None,
                "repo": meta.get("repo") or None,
                "github": meta.get("github") or None,
                "opened_at": meta.get("opened_at"),
                "closed_at": now,
                "turn_count": len(turns),
            }
            await self._push_queue_job(DISTILL_QUEUE_KEY, job)
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

    async def resolve_conversation_session(
        self,
        org_id: UUID | str,
        agent: str,
        fingerprint: str,
        *,
        topic: str | None = None,
        repo: str | None = None,
        github: str | None = None,
    ) -> str:
        """Return the session bound to ``fingerprint``, opening one if needed.

        The gateway proxies stateless chat-completions requests, so it maps
        each distinct conversation (fingerprinted client-side from the first
        user message) to one working session. The mapping key shares the
        session TTL and is refreshed on every hit, so parallel conversations
        from the same agent land in distinct sessions instead of interleaving.
        """
        key = _conversation_key(org_id, agent, fingerprint)
        raw = await self.client.get(key)
        if raw:
            existing = _redis_text(raw)
            try:
                await self._require_open(org_id, existing)
            except (KeyError, ValueError):
                pass
            else:
                await self.client.expire(key, self._default_ttl)
                return existing

        session_id = await self.open_session(
            org_id, agent, topic=topic, repo=repo, github=github
        )
        await self.client.set(key, session_id, ex=self._default_ttl)
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
            meta = _normalize_hash(await client.hgetall(key))
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

    async def queue_stats(self) -> dict[str, int]:
        """Global distill/curate queue depths for metrics and health probes."""
        client = self.client
        return {
            "distill_queue": int(await client.llen(DISTILL_QUEUE_KEY)),
            "distill_dead": int(await client.llen(DISTILL_DEAD_LETTER_KEY)),
            "curate_queue": int(await client.llen(CURATE_QUEUE_KEY)),
            "curate_dead": int(await client.llen(CURATE_DEAD_LETTER_KEY)),
            "curate_pending": int(await client.scard(CURATE_PENDING_KEY)),
        }

    async def list_open_sessions(
        self, org_id: UUID | str, agent: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        ids = cast(
            "list[str]",
            await self.client.zrevrange(_agent_index_key(org_id, agent), 0, limit - 1),
        )
        out: list[dict[str, Any]] = []
        for sid in ids:
            meta = _normalize_hash(await self.client.hgetall(_session_key(org_id, sid)))
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

    async def heartbeat(self, component: str, *, ttl: int = 30) -> None:
        """Stamp a short-TTL liveness key for ``component`` (e.g. ``distiller``)."""
        await self.client.set(
            f"{_HEARTBEAT_PREFIX}{component}",
            datetime.now(UTC).isoformat(),
            ex=ttl,
        )

    async def last_heartbeat(self, component: str) -> str | None:
        """Return the last heartbeat timestamp for ``component`` (None if stale/absent)."""
        return cast("str | None", await self.client.get(f"{_HEARTBEAT_PREFIX}{component}"))

    async def pop_distill_job(self, timeout: int = 5) -> dict[str, Any] | None:
        """Blocking-pop the next distillation job. Returns None on timeout."""
        return await self._pop_queue_job(DISTILL_QUEUE_KEY, DISTILL_DEAD_LETTER_KEY, timeout)

    async def requeue_distill_job(self, job: dict[str, Any]) -> None:
        """Retry a failed distillation job or move it to the dead-letter queue."""
        attempts = int(job.get("attempts", 0)) + 1
        job["attempts"] = attempts
        if attempts >= MAX_DISTILL_ATTEMPTS:
            await self._push_dead_letter(
                DISTILL_DEAD_LETTER_KEY,
                encode_job(job, self._job_signing_secret),
                reason="max_attempts",
            )
            log.error(
                "distill_job_dead_letter",
                session_id=job.get("session_id"),
                attempts=attempts,
            )
            return
        await self._push_queue_job(DISTILL_QUEUE_KEY, job)
        log.warning(
            "distill_job_requeued",
            session_id=job.get("session_id"),
            attempts=attempts,
        )

    async def mark_subject_dirty(
        self, org_id: UUID | str, subject: str, *, threshold: int = 3
    ) -> bool:
        """Count one new fact for ``subject``; enqueue curation on the Nth.

        Debounce: increment a per-subject counter; once it reaches ``threshold``
        reset it and enqueue the subject for (re)curation. Returns True when a
        curation job was enqueued this call.
        """
        subject = (subject or "").strip()
        if not subject:
            return False
        key = _curate_count_key(org_id, subject)
        count = int(await self.client.incr(key))
        await self.client.expire(key, self._default_ttl)
        if count < max(1, threshold):
            return False
        await self.client.delete(key)
        return await self.enqueue_curate(org_id, subject)

    async def enqueue_curate(self, org_id: UUID | str, subject: str) -> bool:
        """Queue ``subject`` for curation unless it is already pending.

        Returns True if newly enqueued, False if a job for it was already queued.
        """
        member = f"{_org(org_id)}::{subject}"
        added = await self.client.sadd(CURATE_PENDING_KEY, member)
        if not added:
            return False
        await self.client.rpush(
            CURATE_QUEUE_KEY,
            encode_job({"org_id": _org(org_id), "subject": subject}, self._job_signing_secret),
        )
        log.info("subject_enqueued_for_curation", org_id=_org(org_id), subject=subject)
        return True

    async def pop_curate_job(self, timeout: int = 5) -> dict[str, Any] | None:
        """Blocking-pop the next curation job; clears its pending flag. None on timeout."""
        job = await self._pop_queue_job(CURATE_QUEUE_KEY, CURATE_DEAD_LETTER_KEY, timeout)
        if job is None:
            return None
        member = f"{job.get('org_id')}::{job.get('subject')}"
        await self.client.srem(CURATE_PENDING_KEY, member)
        return job

    async def requeue_curate_job(self, job: dict[str, Any]) -> None:
        """Retry a failed curation job or move it to the dead-letter queue."""
        attempts = int(job.get("attempts", 0)) + 1
        job["attempts"] = attempts
        if attempts >= MAX_CURATE_ATTEMPTS:
            await self._push_dead_letter(
                CURATE_DEAD_LETTER_KEY,
                encode_job(job, self._job_signing_secret),
                reason="max_attempts",
            )
            log.error("curate_job_dead_letter", subject=job.get("subject"), attempts=attempts)
            return
        await self._push_queue_job(CURATE_QUEUE_KEY, job)
        log.warning("curate_job_requeued", subject=job.get("subject"), attempts=attempts)

    async def _require_open(self, org_id: UUID | str, session_id: str) -> dict[str, str]:
        raw = await self.client.hgetall(_session_key(org_id, session_id))
        if not raw:
            raise KeyError(f"unknown session: {session_id}")
        meta = _normalize_hash(raw)
        if meta.get("closed_at"):
            raise ValueError(f"session {session_id} is closed")
        return meta

    async def _push_queue_job(self, queue_key: str, job: dict[str, Any]) -> None:
        await self.client.rpush(queue_key, encode_job(job, self._job_signing_secret))

    async def _pop_queue_job(
        self, queue_key: str, dead_letter_key: str, timeout: int
    ) -> dict[str, Any] | None:
        result = cast(
            "tuple[str, str] | None",
            await self.client.blpop([queue_key], timeout=timeout),
        )
        if result is None:
            return None
        _, payload = result
        job, err = decode_job(payload, self._job_signing_secret)
        if err is not None:
            await self._reject_queue_job(
                queue_key, dead_letter_key, payload, err,
            )
            return None
        return job

    async def _reject_queue_job(
        self,
        queue_key: str,
        dead_letter_key: str,
        raw_payload: str,
        err: JobSignError,
    ) -> None:
        METRICS.job_signature_invalid.inc(queue=queue_key)
        await self._push_dead_letter(
            dead_letter_key,
            raw_payload,
            reason=str(err),
        )
        if queue_key == CURATE_QUEUE_KEY:
            await self._srem_curate_pending_from_raw(raw_payload)
        log.warning("job_signature_rejected", queue=queue_key, error=str(err))

    async def _srem_curate_pending_from_raw(self, raw_payload: str) -> None:
        """Best-effort pending cleanup when a curate job is rejected or dropped."""
        job = peek_job(raw_payload)
        if not job:
            return
        org_id = job.get("org_id")
        subject = job.get("subject")
        if org_id and subject:
            await self.client.srem(CURATE_PENDING_KEY, f"{org_id}::{subject}")

    async def _push_dead_letter(
        self, dead_letter_key: str, raw_payload: str, *, reason: str
    ) -> None:
        entry = json.dumps({"reason": reason, "raw": raw_payload}, separators=(",", ":"))
        pipe = self.client.pipeline()
        pipe.rpush(dead_letter_key, entry)
        # Keep only the newest entries so a stuck consumer can't grow Redis
        # without bound; depth alerts fire well before the cap (queue_stats).
        pipe.ltrim(dead_letter_key, -DEAD_LETTER_MAX_LEN, -1)
        await pipe.execute()
