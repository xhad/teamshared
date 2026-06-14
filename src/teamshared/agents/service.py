"""Lifecycle facade for background agent runs.

Combines :class:`AgentRunStore` (authoritative state), the Redis
:class:`StreamQueue` (delivery), and :class:`WorkStore` (work-comment events) so
the console and MCP tools stay thin. Every mutating method does (1) a permission
check, (2) a store/queue call, (3) a work-comment timeline event -- and returns
a JSON-serializable dict.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.agents.runs import AgentRunStatus, AgentRunStore
from teamshared.identity.rbac import Permissions
from teamshared.logging import get_logger
from teamshared.memory.request_context import RequestContext
from teamshared.memory.work import WorkStore
from teamshared.queue.streams import StreamQueue

log = get_logger(__name__)

AGENT_RUN_STREAM = "agent:runs"
AGENT_RUN_GROUP = "agent-workers"


class AgentRunNotFoundError(Exception):
    """Raised when a run id does not resolve within the caller's org."""


class AgentRunService:
    def __init__(
        self, runs: AgentRunStore, work: WorkStore, queue: StreamQueue
    ) -> None:
        self.runs = runs
        self.work = work
        self.queue = queue

    async def _comment(
        self, ctx: RequestContext, work_id: UUID, body: str
    ) -> None:
        """Best-effort timeline event; a comment hiccup must not fail the action."""
        try:
            await self.work.add_comment(
                ctx.org_id, work_id,
                author_type=ctx.principal.type,  # type: ignore[arg-type]
                author_id=ctx.principal.id,
                body_md=body,
            )
        except Exception as exc:
            log.warning("agent_run_comment_failed", work_id=str(work_id), error=str(exc))

    async def assign_and_run(
        self,
        ctx: RequestContext,
        *,
        work_id: UUID,
        agent_id: UUID,
        playbook_name: str | None = None,
        playbook_version: int | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        await ctx.authorizer.require(ctx.principal, Permissions.AGENTRUN_WRITE)
        work = await self.work.get(ctx.org_id, work_id)
        if work is None:
            raise AgentRunNotFoundError(f"work item {work_id} not found")

        run = await self.runs.create(
            ctx.org_id,
            work_item_id=work_id,
            agent_id=agent_id,
            created_by=ctx.principal.attribution,
            playbook_name=playbook_name,
            playbook_version=playbook_version,
            model=model,
            provider=provider,
        )
        # Reflect the assignment on the work item so the board shows the agent.
        await self.work.update(
            ctx.org_id, work_id,
            fields={"assignee_type": "agent", "assignee_id": agent_id},
        )
        await self.runs.append_trace(
            ctx.org_id, UUID(str(run["id"])),
            event_type="queued",
            summary="Run queued for background execution.",
            payload={"playbook": playbook_name, "playbook_version": playbook_version},
        )
        enqueued = await self.queue.enqueue(
            AGENT_RUN_STREAM,
            {
                "run_id": str(run["id"]),
                "work_id": str(work_id),
                "agent_id": str(agent_id),
            },
            org_id=str(ctx.org_id),
            trace_id=str(run["id"]),
            idempotency_key=str(run["id"]),
        )
        pb = f" using playbook `{playbook_name}`" if playbook_name else ""
        await self._comment(
            ctx, work_id, f"Queued background agent run{pb} (run `{run['id']}`)."
        )
        log.info(
            "agent_run_created",
            org_id=str(ctx.org_id), run_id=str(run["id"]),
            work_id=str(work_id), enqueued=bool(enqueued),
        )
        return run

    async def cancel(self, ctx: RequestContext, run_id: UUID) -> dict[str, Any]:
        await ctx.authorizer.require(ctx.principal, Permissions.AGENTRUN_WRITE)
        run = await self.runs.request_cancel(ctx.org_id, run_id)
        if run is None:
            raise AgentRunNotFoundError(f"agent run {run_id} not found")
        await self.runs.append_trace(
            ctx.org_id, run_id,
            event_type="cancel_requested",
            summary="Cancellation requested by user.",
        )
        await self._comment(
            ctx, UUID(str(run["work_item_id"])),
            f"Cancellation requested for agent run `{run_id}`.",
        )
        return run

    async def retry(self, ctx: RequestContext, run_id: UUID) -> dict[str, Any]:
        await ctx.authorizer.require(ctx.principal, Permissions.AGENTRUN_WRITE)
        prev = await self.runs.get(ctx.org_id, run_id)
        if prev is None:
            raise AgentRunNotFoundError(f"agent run {run_id} not found")
        return await self.assign_and_run(
            ctx,
            work_id=UUID(str(prev["work_item_id"])),
            agent_id=UUID(str(prev["agent_id"])),
            playbook_name=prev.get("playbook_name"),
            playbook_version=prev.get("playbook_version"),
            model=prev.get("model"),
            provider=prev.get("provider"),
        )

    async def list_runs(
        self,
        ctx: RequestContext,
        *,
        status: AgentRunStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.AGENTRUN_READ)
        return await self.runs.list_for_org(ctx.org_id, status=status, limit=limit)

    async def list_runs_for_work(
        self, ctx: RequestContext, work_id: UUID, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.AGENTRUN_READ)
        return await self.runs.list_for_work(ctx.org_id, work_id, limit=limit)

    async def get_run(self, ctx: RequestContext, run_id: UUID) -> dict[str, Any]:
        await ctx.authorizer.require(ctx.principal, Permissions.AGENTRUN_READ)
        run = await self.runs.get(ctx.org_id, run_id)
        if run is None:
            raise AgentRunNotFoundError(f"agent run {run_id} not found")
        await self.runs.enrich(ctx.org_id, [run])
        run["trace"] = await self.runs.list_trace(ctx.org_id, run_id)
        run["model_calls"] = await self.runs.list_model_calls(ctx.org_id, run_id)
        return run
