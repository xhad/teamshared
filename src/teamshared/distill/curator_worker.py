"""Curation worker entrypoint.

Polls the Redis curate queue, and for each queued subject loads its semantic
facts + recent episodes, asks the curator LLM for a canonical markdown article,
and upserts a new version of the subject's page into ``wiki_pages`` (RLS-scoped
to the job's org). Runs as its own process, like the distillation worker, so the
LLM synthesis never competes with the MCP server.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any
from uuid import UUID

from teamshared.config import Settings, get_settings
from teamshared.distill.curator import curate
from teamshared.distill.summarizer import SummarizerError
from teamshared.logging import configure_logging, get_logger
from teamshared.memory.wiki import slugify
from teamshared.memory.working import WorkingMemory
from teamshared.server.services import ProductionServices, make_services

log = get_logger(__name__)


class CuratorWorker:
    """Long-running consumer for ``working:curate:queue``."""

    _HEARTBEAT_INTERVAL = 10
    _HEARTBEAT_TTL = 30
    _MAX_FACTS = 200
    _MAX_EPISODES = 20

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.working = WorkingMemory(
            settings.redis_url,
            default_ttl=settings.session_ttl,
            job_signing_secret=settings.job_signing_secret,
        )
        self.services: ProductionServices = make_services(settings)
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.working.connect()
        await self.services.tenant_db.connect()
        await self.working.heartbeat("curator", ttl=self._HEARTBEAT_TTL)
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        log.info("curator_worker_started")
        try:
            while not self._stop.is_set():
                try:
                    job = await self.working.pop_curate_job(timeout=5)
                except Exception as exc:
                    log.warning("curate_pop_failed", error=str(exc))
                    await asyncio.sleep(1.0)
                    continue
                if job is None:
                    continue
                try:
                    await self._handle(job)
                except SummarizerError as exc:
                    log.warning("curate_llm_failed", error=str(exc), job=job)
                    await self.working.requeue_curate_job(job)
                except Exception as exc:
                    log.error("curate_job_failed", error=str(exc), job=job)
                    await self.working.requeue_curate_job(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.working.heartbeat("curator", ttl=self._HEARTBEAT_TTL)
            except Exception as exc:
                log.warning("curate_heartbeat_failed", error=str(exc))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._HEARTBEAT_INTERVAL)

    async def stop(self) -> None:
        self._stop.set()
        await self.working.close()
        await self.services.tenant_db.close()
        log.info("curator_worker_stopped")

    async def _handle(self, job: dict[str, Any]) -> None:
        subject = (job.get("subject") or "").strip()
        if not subject:
            return
        org_id = UUID(str(job.get("org_id") or self.settings.default_org_id))
        vs = self.services.vector_store

        fact_records = await vs.list_by_subject(org_id, subject, limit=self._MAX_FACTS)
        if not fact_records:
            log.info("curate_skipping_no_facts", subject=subject, org_id=str(org_id))
            return
        episode_records = await vs.list_episodes(
            org_id=org_id, topic=subject, limit=self._MAX_EPISODES
        )

        facts = [
            {"content": r.content, "kind": r.kind, "confidence": r.confidence,
             "created_at": r.created_at}
            for r in fact_records
        ]
        episodes = [
            {"content": r.content, "created_at": r.created_at} for r in episode_records
        ]

        payload = await curate(
            self.settings, subject=subject, facts=facts, episodes=episodes
        )
        body_md = (payload.get("body_md") or "").strip()
        if not body_md:
            log.info("curate_empty_body", subject=subject)
            return
        title = (payload.get("title") or subject).strip()
        sources = [UUID(r.id) for r in fact_records] + [UUID(r.id) for r in episode_records]

        page = await self.services.wiki.upsert_page(
            org_id, slug=slugify(subject), title=title, body_md=body_md, sources=sources,
        )
        log.info(
            "curate_job_complete", subject=subject, org_id=str(org_id),
            version=page.get("version"), facts=len(facts), episodes=len(episodes),
        )


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = CuratorWorker(settings)

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
