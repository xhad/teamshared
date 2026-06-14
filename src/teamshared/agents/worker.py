"""Background agent-run worker entrypoint.

Consumes the ``agent:runs`` Redis Stream with a consumer group, leases each run
through the authoritative DB guard (so a duplicate delivery never double-runs),
and executes it single-shot via :class:`AgentRunner`. Crash recovery uses
``XAUTOCLAIM`` to reclaim messages a dead worker left pending; the lease's
``status``/``lease_expires_at`` make reprocessing idempotent.

Runs as its own process (like the distiller/curator) so a long model call never
competes with the MCP server's event loop. Heartbeats to Redis under the
``agent-worker`` component so ``/health`` can report liveness.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
from typing import Any
from uuid import UUID

from teamshared.agents.runner import AgentRunner
from teamshared.agents.runs import AgentRunStore
from teamshared.agents.service import AGENT_RUN_GROUP, AGENT_RUN_STREAM
from teamshared.config import Settings, get_settings
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.logging import configure_logging, get_logger
from teamshared.memory.agent_state import AgentStateStore
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.graph import GraphStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.strategic import OrgStrategicStore
from teamshared.memory.working import WorkingMemory
from teamshared.queue.streams import StreamQueue
from teamshared.server.services import ProductionServices, make_services

log = get_logger(__name__)


class AgentWorker:
    """Long-running consumer for the ``agent:runs`` stream."""

    _HEARTBEAT_INTERVAL = 10
    _HEARTBEAT_TTL = 30
    _LEASE_BUFFER = 60
    _RECLAIM_EVERY = 6  # reclaim stale pending entries roughly every N polls

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.consumer = f"agent-worker-{socket.gethostname()}-{id(self)}"
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
        self.runs = AgentRunStore(self.services.tenant_db)
        self._queue: StreamQueue | None = None
        self._runner: AgentRunner | None = None
        self._graph: GraphStore | None = None
        self._stop = asyncio.Event()

    @property
    def queue(self) -> StreamQueue:
        assert self._queue is not None
        return self._queue

    @property
    def runner(self) -> AgentRunner:
        assert self._runner is not None
        return self._runner

    async def start(self) -> None:
        await self.working.connect()
        await self.services.tenant_db.connect()
        self._queue = StreamQueue(self.working.client)
        await self.queue.ensure_group(AGENT_RUN_STREAM, AGENT_RUN_GROUP)

        graph = GraphStore(
            self.settings.neo4j_url, self.settings.neo4j_user, self.settings.neo4j_password
        )
        try:
            await graph.connect()
            self._graph = graph
        except Exception as exc:
            log.warning("agent_worker_graph_unavailable", error=str(exc))
            self._graph = None

        facade = MemoryFacade(
            services=self.services,
            resolver=self.resolver,
            working=self.working,
            agent_state=AgentStateStore(self.working.client),
            procedural=OrgProceduralStore(self.services.tenant_db),
            strategic=OrgStrategicStore(self.services.tenant_db),
            graph=self._graph,
        )
        self._runner = AgentRunner(
            settings=self.settings,
            runs=self.runs,
            facade=facade,
            work=self.services.work,
            procedural=self.services.procedural,
            ingestion=self.services.ingestion(),
        )

        await self.working.heartbeat("agent-worker", ttl=self._HEARTBEAT_TTL)
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        log.info("agent_worker_started", consumer=self.consumer)
        polls = 0
        try:
            while not self._stop.is_set():
                try:
                    if polls % self._RECLAIM_EVERY == 0:
                        for job in await self.queue.claim_stale(
                            AGENT_RUN_STREAM, AGENT_RUN_GROUP, self.consumer
                        ):
                            await self._dispatch(job)
                    jobs = await self.queue.read(
                        AGENT_RUN_STREAM, AGENT_RUN_GROUP, self.consumer,
                        count=1, block_ms=5000,
                    )
                except Exception as exc:
                    log.warning("agent_worker_read_failed", error=str(exc))
                    await asyncio.sleep(1.0)
                    continue
                polls += 1
                for job in jobs:
                    await self._dispatch(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _dispatch(self, job: Any) -> None:
        """Lease + execute one job, then ack. Lease guards against double-run."""
        payload = job.payload or {}
        run_id_raw = payload.get("run_id")
        org_id_raw = payload.get("org_id") or job.org_id
        if not run_id_raw or not org_id_raw:
            log.warning("agent_worker_bad_job", job_id=job.id)
            await self.queue.ack(AGENT_RUN_STREAM, AGENT_RUN_GROUP, job.id)
            return
        org_id = UUID(str(org_id_raw))
        run_id = UUID(str(run_id_raw))
        lease_ttl = self.settings.agent_run_timeout_seconds + self._LEASE_BUFFER
        try:
            run = await self.runs.lease(
                org_id, run_id, owner=self.consumer, ttl_seconds=lease_ttl
            )
            if run is None:
                # Already owned, finished, or cancelled -- nothing to do.
                await self.queue.ack(AGENT_RUN_STREAM, AGENT_RUN_GROUP, job.id)
                return
            await asyncio.wait_for(
                self.runner.execute(run),
                timeout=self.settings.agent_run_timeout_seconds,
            )
        except TimeoutError:
            log.warning("agent_worker_run_timeout", run_id=str(run_id))
            with contextlib.suppress(Exception):
                await self.runs.mark(
                    org_id, run_id, status="failed",
                    error="Run exceeded the time budget and was stopped.",
                )
                await self.runs.append_trace(
                    org_id, run_id, event_type="failed", summary="Run timed out.",
                )
        except Exception as exc:
            log.error("agent_worker_run_error", run_id=str(run_id), error=str(exc))
            with contextlib.suppress(Exception):
                await self.runs.mark(
                    org_id, run_id, status="failed", error=str(exc)[:500],
                )
                await self.runs.append_trace(
                    org_id, run_id, event_type="failed",
                    summary="Run failed with an unexpected worker error.",
                    payload={"error": str(exc)[:500]},
                )
        finally:
            await self.queue.ack(AGENT_RUN_STREAM, AGENT_RUN_GROUP, job.id)

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.working.heartbeat("agent-worker", ttl=self._HEARTBEAT_TTL)
            except Exception as exc:
                log.warning("agent_worker_heartbeat_failed", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._HEARTBEAT_INTERVAL
                )

    async def stop(self) -> None:
        self._stop.set()
        await self.working.close()
        await self.services.tenant_db.close()
        if self._graph is not None:
            with contextlib.suppress(Exception):
                await self._graph.close()
        log.info("agent_worker_stopped")


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = AgentWorker(settings)

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
