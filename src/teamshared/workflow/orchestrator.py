"""Drive work items through a workflow's stage graph (the procedural loop).

The orchestrator is the only place that interprets the validated stage graph
(:mod:`teamshared.workflow.definition`). It reuses the existing single-shot
``agent_runs`` executor for agent stages and gates human stages until a teammate
calls :meth:`advance`. Routing can send an item back to an earlier stage; a run
loops over its item set until every item is terminal or ``max_iterations`` is
hit.

Driver policy (hybrid):

* **agent stage, ``advance=auto``** -- on agent-run completion the item is routed
  automatically via ``on_done``.
* **agent stage, ``advance=manual``** -- the agent runs, then a human gate is
  opened at the same stage; a teammate approves/rejects to route.
* **human stage** -- a ``waiting_human`` step is opened immediately; the item
  moves only when a teammate calls :meth:`advance`.

All mutating entry points (:meth:`start`, :meth:`advance`, :meth:`cancel`)
require ``workflow:write``. :meth:`on_step_complete` runs inside the agent worker
under the agent's own principal (which already holds ``agentrun:write``).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from teamshared.agents.service import AgentRunService
from teamshared.identity.rbac import Permissions
from teamshared.logging import get_logger
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.request_context import RequestContext
from teamshared.memory.work import WorkStore
from teamshared.workflow.definition import (
    TERMINAL_TARGETS,
    Stage,
    WorkflowDefinition,
    WorkflowDefinitionError,
    parse_definition,
)
from teamshared.workflow.runs import WorkflowRunStore

log = get_logger(__name__)

_DEFAULT_MAX_ITERATIONS = 10


class WorkflowError(Exception):
    """Raised when a workflow cannot be started or advanced."""


class WorkflowOrchestrator:
    """Stateless coordinator; construct once and reuse across requests/runs."""

    def __init__(
        self,
        *,
        runs: WorkflowRunStore,
        work: WorkStore,
        procedural: OrgProceduralStore,
        agent_runs: AgentRunService,
    ) -> None:
        self.runs = runs
        self.work = work
        self.procedural = procedural
        self.agent_runs = agent_runs

    # -- public entry points ----------------------------------------------

    async def start(
        self,
        ctx: RequestContext,
        *,
        workflow_name: str,
        version: int | None = None,
        work_ids: list[UUID] | None = None,
        selector: dict[str, Any] | None = None,
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        await ctx.authorizer.require(ctx.principal, Permissions.WORKFLOW_WRITE)
        proc = await self.procedural.get_procedure(ctx.org_id, workflow_name, version)
        if proc is None:
            raise WorkflowError(
                f"workflow '{workflow_name}' is unavailable (missing, pending "
                "approval, or quarantined)"
            )
        try:
            definition = parse_definition(proc.get("tool_recipe"))
        except WorkflowDefinitionError as exc:
            raise WorkflowError(
                f"procedure '{workflow_name}' is not a valid workflow: {exc}"
            ) from exc

        effective_selector = selector or (
            definition.loop.select if definition.loop else None
        )
        items = await self._resolve_items(ctx, work_ids, effective_selector)
        loop_max = definition.loop.max_iterations if definition.loop else _DEFAULT_MAX_ITERATIONS
        max_it = max_iterations or loop_max

        run = await self.runs.create_run(
            ctx.org_id,
            workflow_name=proc["name"],
            workflow_version=proc.get("version"),
            created_by=ctx.principal.attribution,
            selector=effective_selector or {},
            max_iterations=max_it,
        )
        run_id = UUID(str(run["id"]))
        for work_id in items:
            await self._enter_stage(ctx, run, definition, work_id, definition.first)
        await self._maybe_complete_run(ctx, run_id)

        out = await self.runs.get_run(ctx.org_id, run_id) or run
        out["work_item_count"] = len(items)
        log.info(
            "workflow_started",
            org_id=str(ctx.org_id), run_id=str(run_id),
            workflow=proc["name"], items=len(items),
        )
        return out

    async def advance(
        self, ctx: RequestContext, *, step_id: UUID, decision: str
    ) -> dict[str, Any]:
        """Resolve a ``waiting_human`` gate (``decision`` = approve | reject)."""
        await ctx.authorizer.require(ctx.principal, Permissions.WORKFLOW_WRITE)
        if decision not in ("approve", "reject"):
            raise WorkflowError("decision must be 'approve' or 'reject'")
        step = await self.runs.get_step(ctx.org_id, step_id)
        if step is None:
            raise WorkflowError(f"workflow step {step_id} not found")
        if step["owner"] != "human" or step["status"] != "waiting_human":
            raise WorkflowError("step is not awaiting a human decision")
        run = await self.runs.get_run(ctx.org_id, UUID(str(step["workflow_run_id"])))
        if run is None or run["status"] != "running":
            raise WorkflowError("workflow run is not active")
        run_id = UUID(str(run["id"]))
        work_id = UUID(str(step["work_item_id"]))

        await self.runs.mark_step(
            ctx.org_id, step_id, status="done", note=f"human {decision}"
        )
        definition = await self._definition_for_run(ctx, run)
        stage = definition.stage(step["stage_id"]) if definition else None
        if definition is not None and stage is not None:
            await self._route(ctx, run, definition, stage, work_id, decision=decision)
        else:
            await self._terminate_item(ctx, run_id, work_id, "done")
        await self._maybe_complete_run(ctx, run_id)
        return await self.runs.get_run(ctx.org_id, run_id) or run

    async def on_step_complete(
        self,
        ctx: RequestContext,
        *,
        agent_run_id: UUID,
        success: bool,
        summary: str | None = None,
    ) -> None:
        """Auto-advance the workflow item an agent run belongs to (worker hook).

        A no-op when the run is not part of a workflow, so it is safe to call
        unconditionally from the agent runner.
        """
        step = await self.runs.step_for_agent_run(ctx.org_id, agent_run_id)
        if step is None or step.get("status") != "running":
            return
        run = await self.runs.get_run(ctx.org_id, UUID(str(step["workflow_run_id"])))
        if run is None or run["status"] != "running":
            return
        run_id = UUID(str(run["id"]))
        step_id = UUID(str(step["id"]))
        work_id = UUID(str(step["work_item_id"]))
        definition = await self._definition_for_run(ctx, run)
        stage = definition.stage(step["stage_id"]) if definition else None

        if definition is None or stage is None:
            await self.runs.mark_step(
                ctx.org_id, step_id, status="failed",
                note="stage missing from workflow definition",
            )
            await self._maybe_complete_run(ctx, run_id)
            return

        if not success:
            await self.runs.mark_step(ctx.org_id, step_id, status="failed")
            await self._comment(
                ctx, work_id,
                f"Workflow stage `{stage.id}` agent run failed; item paused.",
            )
            await self._maybe_complete_run(ctx, run_id)
            return

        await self.runs.mark_step(ctx.org_id, step_id, status="done")
        if stage.advance == "manual":
            await self.runs.create_step(
                ctx.org_id,
                workflow_run_id=run_id, work_item_id=work_id, stage_id=stage.id,
                owner="human", status="waiting_human",
                note="agent run done; awaiting approval",
            )
            await self._comment(
                ctx, work_id,
                f"Workflow stage `{stage.id}` finished its agent run and is "
                "awaiting approval (workflow_advance).",
            )
            return

        await self._route(ctx, run, definition, stage, work_id, decision="done")
        await self._maybe_complete_run(ctx, run_id)

    async def cancel(self, ctx: RequestContext, *, run_id: UUID) -> dict[str, Any]:
        await ctx.authorizer.require(ctx.principal, Permissions.WORKFLOW_WRITE)
        run = await self.runs.get_run(ctx.org_id, run_id)
        if run is None:
            raise WorkflowError(f"workflow run {run_id} not found")
        for step in await self.runs.list_steps_for_run(ctx.org_id, run_id):
            if step["status"] in ("pending", "running", "waiting_human"):
                await self.runs.mark_step(
                    ctx.org_id, UUID(str(step["id"])), status="skipped",
                    note="workflow run cancelled",
                )
            await self.runs.set_work_pointer(
                ctx.org_id, UUID(str(step["work_item_id"])), run_id=run_id, stage=None
            )
        return await self.runs.mark_run(ctx.org_id, run_id, status="cancelled") or run

    # -- stage handling ----------------------------------------------------

    async def _enter_stage(
        self,
        ctx: RequestContext,
        run: dict[str, Any],
        definition: WorkflowDefinition,
        work_id: UUID,
        stage: Stage,
    ) -> None:
        run_id = UUID(str(run["id"]))
        await self.runs.set_work_pointer(ctx.org_id, work_id, run_id=run_id, stage=stage.id)

        if stage.owner == "human":
            await self.runs.create_step(
                ctx.org_id,
                workflow_run_id=run_id, work_item_id=work_id, stage_id=stage.id,
                owner="human", status="waiting_human",
            )
            await self.work.update(ctx.org_id, work_id, fields={"work_status": "todo"})
            await self._comment(
                ctx, work_id,
                f"Workflow stage `{stage.id}` is awaiting a human decision "
                "(workflow_advance with approve|reject).",
            )
            return

        agent_id = await self._resolve_stage_agent(ctx, stage, work_id)
        if agent_id is None:
            await self.runs.create_step(
                ctx.org_id,
                workflow_run_id=run_id, work_item_id=work_id, stage_id=stage.id,
                owner="agent", status="failed",
                note=f"no agent resolved for stage '{stage.id}'",
            )
            await self._comment(
                ctx, work_id,
                f"Workflow stage `{stage.id}` could not start: no agent resolved.",
            )
            return

        step = await self.runs.create_step(
            ctx.org_id,
            workflow_run_id=run_id, work_item_id=work_id, stage_id=stage.id,
            owner="agent", status="running",
        )
        await self.work.update(ctx.org_id, work_id, fields={"work_status": "in_progress"})
        agent_run = await self.agent_runs.assign_and_run(
            ctx,
            work_id=work_id, agent_id=agent_id,
            playbook_name=stage.playbook, playbook_version=stage.playbook_version,
        )
        await self.runs.mark_step(
            ctx.org_id, UUID(str(step["id"])),
            agent_run_id=UUID(str(agent_run["id"])),
        )

    async def _route(
        self,
        ctx: RequestContext,
        run: dict[str, Any],
        definition: WorkflowDefinition,
        stage: Stage,
        work_id: UUID,
        *,
        decision: str,
    ) -> None:
        run_id = UUID(str(run["id"]))
        target = stage.next_target(decision)
        if decision == "reject" and target is None:
            target = stage.id  # reject with no explicit target re-runs the stage
        if target is None:
            target = "done"

        if target in TERMINAL_TARGETS:
            await self._terminate_item(ctx, run_id, work_id, target)
            return

        next_stage = definition.stage(target)
        if next_stage is None:
            await self._terminate_item(ctx, run_id, work_id, "done")
            return

        if _is_loop_back(definition, stage, next_stage):
            iteration = await self.runs.bump_iteration(ctx.org_id, run_id)
            max_it = int(run.get("max_iterations") or _DEFAULT_MAX_ITERATIONS)
            if iteration >= max_it:
                await self._comment(
                    ctx, work_id,
                    f"Workflow reached its iteration limit ({max_it}); closing task.",
                )
                await self._terminate_item(ctx, run_id, work_id, "done")
                return

        await self._enter_stage(ctx, run, definition, work_id, next_stage)

    async def _terminate_item(
        self, ctx: RequestContext, run_id: UUID, work_id: UUID, target: str
    ) -> None:
        work_status: Literal["done", "cancelled"] = (
            "cancelled" if target == "cancelled" else "done"
        )
        await self.work.close(ctx.org_id, work_id, work_status=work_status)
        await self.runs.set_work_pointer(ctx.org_id, work_id, run_id=run_id, stage=None)
        await self._comment(
            ctx, work_id, f"Workflow closed this task ({work_status})."
        )

    async def _maybe_complete_run(self, ctx: RequestContext, run_id: UUID) -> None:
        if await self.runs.has_open_steps(ctx.org_id, run_id):
            return
        await self.runs.mark_run(ctx.org_id, run_id, status="completed")
        log.info("workflow_completed", org_id=str(ctx.org_id), run_id=str(run_id))

    # -- helpers -----------------------------------------------------------

    async def _resolve_items(
        self,
        ctx: RequestContext,
        work_ids: list[UUID] | None,
        selector: dict[str, Any] | None,
    ) -> list[UUID]:
        if work_ids is not None:
            return list(work_ids)
        if not selector:
            raise WorkflowError(
                "workflow needs explicit work_ids or a selector (from the "
                "definition's loop.select or the start call)"
            )
        initiative = selector.get("initiative_id")
        project = selector.get("project_id")
        items = await self.work.list_items(
            ctx.org_id,
            work_status=selector.get("work_status"),
            initiative_id=UUID(str(initiative)) if initiative else None,
            project_id=UUID(str(project)) if project else None,
            limit=int(selector.get("limit", 50)),
        )
        return [UUID(str(item["id"])) for item in items]

    async def _resolve_stage_agent(
        self, ctx: RequestContext, stage: Stage, work_id: UUID
    ) -> UUID | None:
        if stage.agent:
            agent_id = await self.work.resolve_agent_id(ctx.org_id, stage.agent)
            if agent_id is not None:
                return UUID(str(agent_id))
        work = await self.work.get(ctx.org_id, work_id)
        if work and work.get("assignee_type") == "agent" and work.get("assignee_id"):
            return UUID(str(work["assignee_id"]))
        return None

    async def _definition_for_run(
        self, ctx: RequestContext, run: dict[str, Any]
    ) -> WorkflowDefinition | None:
        proc = await self.procedural.get_procedure(
            ctx.org_id, run["workflow_name"], run.get("workflow_version")
        )
        if proc is None:
            return None
        try:
            return parse_definition(proc.get("tool_recipe"))
        except WorkflowDefinitionError:
            return None

    async def _comment(
        self, ctx: RequestContext, work_id: UUID, body: str
    ) -> None:
        try:
            await self.work.add_comment(
                ctx.org_id, work_id,
                author_type=ctx.principal.type,  # type: ignore[arg-type]
                author_id=ctx.principal.id,
                body_md=body,
            )
        except Exception as exc:  # a comment hiccup must not break orchestration
            log.warning("workflow_comment_failed", work_id=str(work_id), error=str(exc))


def _is_loop_back(
    definition: WorkflowDefinition, stage: Stage, next_stage: Stage
) -> bool:
    """True when routing to a stage at or before the current one (a loop)."""
    ids = [s.id for s in definition.stages]
    return ids.index(next_stage.id) <= ids.index(stage.id)
