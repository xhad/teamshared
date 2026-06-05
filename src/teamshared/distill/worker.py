"""Distillation worker entrypoint.

Polls the Redis distill queue, pulls each job, fetches its transcript, asks
the summarizer for structured output, and writes the result back through the
org-scoped ingestion pipeline (pgvector + RLS) as a single episodic memory
plus N semantic facts. Each job carries its ``org_id`` so distilled memory
lands in the right tenant under the originating agent's attribution. Runs as
its own process so it never competes with the MCP server for CPU/event-loop
slices.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any
from uuid import UUID

from teamshared.config import Settings, get_settings
from teamshared.distill.summarizer import SummarizerError, summarize
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.logging import configure_logging, get_logger
from teamshared.memory.agent_state import github_tag, repo_tag
from teamshared.memory.request_context import RequestContext
from teamshared.memory.working import WorkingMemory
from teamshared.server.services import ProductionServices, make_services

log = get_logger(__name__)


class DistillWorker:
    """Long-running consumer for ``working:distill:queue``."""

    # Liveness: beat every _HEARTBEAT_INTERVAL with a _HEARTBEAT_TTL key so the
    # /health probe reports the worker as up even mid-job (a long summarize()
    # call must not let the heartbeat lapse), and as down within the TTL once
    # the process exits.
    _HEARTBEAT_INTERVAL = 10
    _HEARTBEAT_TTL = 30

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.working = WorkingMemory(
            settings.redis_url,
            default_ttl=settings.session_ttl,
            job_signing_secret=settings.job_signing_secret,
        )
        self.services: ProductionServices = make_services(settings)
        self.resolver = PrincipalResolver(
            api_keys=self.services.api_keys,
            roles=self.services.roles,
            tenant_db=self.services.tenant_db,
            default_org_id=settings.default_org_id,
            session_secret=settings.session_secret,
        )
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.working.connect()
        await self.services.tenant_db.connect()
        await self.working.heartbeat("distiller", ttl=self._HEARTBEAT_TTL)
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        log.info("distill_worker_started")
        try:
            while not self._stop.is_set():
                try:
                    job = await self.working.pop_distill_job(timeout=5)
                except Exception as exc:
                    log.warning("distill_pop_failed", error=str(exc))
                    await asyncio.sleep(1.0)
                    continue
                if job is None:
                    continue
                try:
                    await self._handle(job)
                except SummarizerError as exc:
                    log.warning("distill_summarizer_failed", error=str(exc), job=job)
                    await self.working.requeue_distill_job(job)
                except Exception as exc:
                    log.error("distill_job_failed", error=str(exc), job=job)
                    await self.working.requeue_distill_job(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.working.heartbeat("distiller", ttl=self._HEARTBEAT_TTL)
            except Exception as exc:
                log.warning("distill_heartbeat_failed", error=str(exc))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._HEARTBEAT_INTERVAL)

    async def stop(self) -> None:
        self._stop.set()
        await self.working.close()
        await self.services.tenant_db.close()
        log.info("distill_worker_stopped")

    async def _handle(self, job: dict[str, Any]) -> None:
        session_id = job["session_id"]
        agent = job.get("agent") or "unknown"
        topic = job.get("topic")
        org_id = UUID(str(job.get("org_id") or self.settings.default_org_id))

        # Distilled memories inherit session workspace/github scope when set.
        scope_tags: list[str] = []
        if job.get("repo"):
            try:
                scope_tags.append(repo_tag(str(job["repo"])))
            except ValueError:
                log.warning("distill_repo_invalid", repo=job.get("repo"))
        if job.get("github"):
            try:
                scope_tags.append(github_tag(str(job["github"])))
            except ValueError:
                log.warning("distill_github_invalid", github=job.get("github"))

        transcript = await self.working.get_turns(org_id, session_id)
        if not transcript:
            log.info("distill_skipping_empty", session_id=session_id)
            return

        payload = await summarize(
            self.settings, agent=agent, topic=topic, transcript=transcript
        )

        episode = payload.get("episode") or {}
        facts = payload.get("facts") or []
        decisions = payload.get("decisions") or []

        # Distilled memory is attributed to the originating agent within its org.
        principal = await self.resolver.agent_principal(org_id, agent)
        ctx = RequestContext(
            principal=principal,
            db=self.services.tenant_db,
            authorizer=self.services.authorizer(),
        )
        ingestion = self.services.ingestion()

        if episode.get("summary"):
            await ingestion.ingest(
                ctx, episode["summary"], kind="event", pillar="episodic",
                scope="org", subject=topic,
                tags=list(episode.get("tags") or []) + scope_tags,
                source="agent",
                source_ref={"session_id": session_id, "outcome": episode.get("outcome")},
            )

        for fact in facts:
            content = (fact.get("content") or "").strip()
            if not content:
                continue
            await ingestion.ingest(
                ctx, content, kind=fact.get("kind") or "fact", pillar="semantic",
                scope="org", subject=fact.get("subject"),
                tags=scope_tags or None, source="agent",
                confidence=fact.get("confidence"),
                source_ref={"session_id": session_id},
            )

        for decision in decisions:
            content = (decision.get("content") or "").strip()
            if not content:
                continue
            await ingestion.ingest(
                ctx, content, kind="fact", pillar="semantic", scope="org",
                subject=topic, tags=["decision"] + scope_tags, source="agent",
                source_ref={"session_id": session_id, "rationale": decision.get("rationale")},
            )

        # Feed the wiki: count new facts per subject and enqueue (debounced)
        # curation when a subject crosses the threshold. Best-effort; a curation
        # hiccup must never fail the distill job.
        subjects = {f.get("subject") for f in facts if f.get("subject")}
        if topic and decisions:
            subjects.add(topic)
        threshold = getattr(self.settings, "curate_threshold", 3)
        for subject in subjects:
            try:
                await self.working.mark_subject_dirty(org_id, subject, threshold=threshold)
            except Exception as exc:
                log.warning("curate_enqueue_failed", subject=subject, error=str(exc))

        log.info(
            "distill_job_complete",
            session_id=session_id,
            org_id=str(org_id),
            facts=len(facts),
            decisions=len(decisions),
            episode=bool(episode.get("summary")),
        )


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = DistillWorker(settings)

    loop = asyncio.get_running_loop()
    stop_signal = asyncio.Event()

    def _request_stop() -> None:
        stop_signal.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)

    runner = asyncio.create_task(worker.start())
    await stop_signal.wait()
    await worker.stop()
    await runner


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
