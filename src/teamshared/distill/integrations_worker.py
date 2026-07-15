"""Integrations sync worker entrypoint.

Periodically polls every connected Gmail/Slack connector across all orgs,
refreshes its OAuth access token if needed, and syncs new messages into the
org's shared brain via the ingestion pipeline (``source='connector'``).

Runs as its own process (like the distiller/curator), writing a Redis
heartbeat so ``teamshared worker-health integrations-sync`` can probe liveness.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any
from uuid import UUID

from teamshared.config import Settings, get_settings
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.logging import configure_logging, get_logger
from teamshared.memory.request_context import RequestContext
from teamshared.memory.working import WorkingMemory
from teamshared.server.services import ProductionServices, make_services

log = get_logger(__name__)

COMPONENT = "integrations-sync"
_INTEGRATION_KINDS = ("gmail", "slack")


class IntegrationsWorker:
    """Long-running poller that syncs connected Gmail/Slack accounts."""

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
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.working.connect()
        await self.services.tenant_db.connect()
        await self.working.heartbeat(COMPONENT, ttl=self._HEARTBEAT_TTL)
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        interval = self.settings.integrations_sync_interval_seconds
        log.info("integrations_worker_started", interval=interval)
        try:
            while not self._stop.is_set():
                try:
                    await self._sync_all_due()
                except Exception as exc:  # noqa: BLE001
                    log.error("integrations_sync_cycle_failed", error=str(exc))
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.working.heartbeat(COMPONENT, ttl=self._HEARTBEAT_TTL)
            except Exception as exc:  # noqa: BLE001
                log.warning("integrations_heartbeat_failed", error=str(exc))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._HEARTBEAT_INTERVAL)

    async def stop(self) -> None:
        self._stop.set()
        await self.working.close()
        await self.services.tenant_db.close()
        log.info("integrations_worker_stopped")

    async def _list_due_connectors(self) -> list[tuple[UUID, UUID, str, dict[str, Any]]]:
        """Return (org_id, connector_id, kind, config) for connected integration connectors.

        Uses the admin connection to cross orgs (RLS bypass is intentional for
        the worker, same as the reembed command).
        """
        rows: list[tuple[UUID, UUID, str, dict[str, Any]]] = []
        async with self.services.tenant_db.admin() as conn:
            cur = await conn.execute(
                "SELECT org_id, id, kind, config FROM connectors "
                "WHERE status = 'connected' AND kind = ANY(%s)",
                (list(_INTEGRATION_KINDS),),
            )
            for r in await cur.fetchall():
                rows.append((UUID(str(r[0])), UUID(str(r[1])), r[2], r[3] or {}))
        return rows

    async def _sync_all_due(self) -> None:
        due = await self._list_due_connectors()
        if not due:
            return
        resolver = PrincipalResolver(
            api_keys=self.services.api_keys,
            roles=self.services.roles,
            tenant_db=self.services.tenant_db,
            default_org_id=self.settings.default_org_id,
            session_secret=self.settings.session_secret,
        )
        for org_id, connector_id, kind, _config in due:
            try:
                principal = await resolver.agent_principal(org_id, "integrations-sync")
                ctx = RequestContext(
                    principal=principal,
                    db=self.services.tenant_db,
                    authorizer=self.services.authorizer(),
                )
                report = await self.services.connectors.sync(ctx, connector_id)
                log.info(
                    "integrations_connector_synced",
                    connector_id=str(connector_id), org_id=str(org_id), kind=kind,
                    fetched=report.fetched, imported=report.imported,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "integrations_connector_sync_failed",
                    connector_id=str(connector_id), org_id=str(org_id), kind=kind,
                    error=str(exc),
                )


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = IntegrationsWorker(settings)

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
