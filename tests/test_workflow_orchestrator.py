"""Unit tests for the procedural-loop orchestrator (in-memory fakes, no DB).

These pin the routing/loop semantics: agent stages dispatch a run and
auto-advance on completion, human stages gate until ``advance``, rejection can
loop an item back to an earlier stage, and the run completes once every item is
terminal (or the iteration cap is hit).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from teamshared.identity.principal import Principal
from teamshared.memory.request_context import RequestContext
from teamshared.workflow.definition import WorkflowDefinitionError, parse_definition
from teamshared.workflow.orchestrator import WorkflowError, WorkflowOrchestrator

ORG = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def _ctx() -> RequestContext:
    principal = Principal(
        org_id=ORG, type="agent", id=AGENT_ID, display="cursor", roles=("agent",)
    )
    authorizer = MagicMock()
    authorizer.require = AsyncMock()
    return RequestContext(principal=principal, db=MagicMock(), authorizer=authorizer)


class FakeWorkflowRunStore:
    """Minimal in-memory stand-in for WorkflowRunStore."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.steps: dict[str, dict[str, Any]] = {}
        self.pointers: dict[str, dict[str, Any]] = {}

    async def create_run(
        self, org_id, *, workflow_name, created_by, workflow_version=None,
        selector=None, initiative_id=None, project_id=None, max_iterations=10,
    ) -> dict[str, Any]:
        run_id = uuid4()
        row = {
            "id": run_id, "org_id": org_id, "workflow_name": workflow_name,
            "workflow_version": workflow_version, "status": "running",
            "iteration": 0, "max_iterations": max_iterations,
            "selector_json": selector or {}, "created_by": created_by,
            "created_at": datetime.now(UTC), "completed_at": None, "error": None,
        }
        self.runs[str(run_id)] = row
        return dict(row)

    async def get_run(self, org_id, run_id) -> dict[str, Any] | None:
        row = self.runs.get(str(run_id))
        return dict(row) if row else None

    async def list_runs(self, org_id, *, status=None, limit=50):
        return [dict(r) for r in self.runs.values()]

    async def mark_run(self, org_id, run_id, *, status=None, **fields):
        row = self.runs.get(str(run_id))
        if row is None:
            return None
        if status is not None:
            row["status"] = status
        row.update({k: v for k, v in fields.items()})
        return dict(row)

    async def bump_iteration(self, org_id, run_id) -> int:
        row = self.runs[str(run_id)]
        row["iteration"] += 1
        return int(row["iteration"])

    async def create_step(
        self, org_id, *, workflow_run_id, work_item_id, stage_id, owner,
        status="pending", agent_run_id=None, note=None,
    ) -> dict[str, Any]:
        seq = max(
            (
                s["seq"] + 1
                for s in self.steps.values()
                if str(s["workflow_run_id"]) == str(workflow_run_id)
                and str(s["work_item_id"]) == str(work_item_id)
                and s["stage_id"] == stage_id
            ),
            default=0,
        )
        step_id = uuid4()
        row = {
            "id": step_id, "org_id": org_id, "workflow_run_id": workflow_run_id,
            "work_item_id": work_item_id, "stage_id": stage_id, "owner": owner,
            "status": status, "seq": seq, "agent_run_id": agent_run_id,
            "note": note, "created_at": datetime.now(UTC), "completed_at": None,
        }
        self.steps[str(step_id)] = row
        return dict(row)

    async def get_step(self, org_id, step_id) -> dict[str, Any] | None:
        row = self.steps.get(str(step_id))
        return dict(row) if row else None

    async def step_for_agent_run(self, org_id, agent_run_id) -> dict[str, Any] | None:
        matches = [
            s for s in self.steps.values()
            if s.get("agent_run_id") and str(s["agent_run_id"]) == str(agent_run_id)
        ]
        matches.sort(key=lambda s: s["seq"], reverse=True)
        return dict(matches[0]) if matches else None

    async def mark_step(self, org_id, step_id, *, status=None, **fields):
        row = self.steps.get(str(step_id))
        if row is None:
            return None
        if status is not None:
            row["status"] = status
            if status in ("done", "failed", "skipped"):
                row["completed_at"] = datetime.now(UTC)
        row.update({k: v for k, v in fields.items()})
        return dict(row)

    async def list_steps_for_run(self, org_id, run_id):
        rows = [
            s for s in self.steps.values()
            if str(s["workflow_run_id"]) == str(run_id)
        ]
        rows.sort(key=lambda s: (s["created_at"], s["seq"]))
        return [dict(r) for r in rows]

    async def has_open_steps(self, org_id, run_id) -> bool:
        return any(
            str(s["workflow_run_id"]) == str(run_id)
            and s["status"] in ("pending", "running", "waiting_human")
            for s in self.steps.values()
        )

    async def set_work_pointer(self, org_id, work_id, *, run_id, stage):
        self.pointers[str(work_id)] = {"run_id": run_id, "stage": stage}


class FakeWorkStore:
    def __init__(self, items: dict[str, dict[str, Any]] | None = None) -> None:
        self.items = items or {}
        self.comments: list[dict[str, Any]] = []

    async def get(self, org_id, work_id):
        return dict(self.items.get(str(work_id), {"id": work_id})) or None

    async def update(self, org_id, work_id, *, fields):
        self.items.setdefault(str(work_id), {"id": work_id}).update(fields)
        return self.items[str(work_id)]

    async def close(self, org_id, work_id, *, work_status="done"):
        item = self.items.setdefault(str(work_id), {"id": work_id})
        item["work_status"] = work_status
        item["closed_at"] = datetime.now(UTC)
        return item

    async def resolve_agent_id(self, org_id, name):
        return AGENT_ID  # every named agent resolves in tests

    async def add_comment(self, org_id, work_id, *, author_type, author_id, body_md):
        self.comments.append({"work_id": work_id, "body": body_md})
        return {"id": uuid4()}

    async def list_items(self, org_id, *, work_status=None, initiative_id=None,
                         project_id=None, limit=50):
        out = []
        for item in self.items.values():
            if work_status and item.get("work_status") != work_status:
                continue
            out.append(item)
        return out[:limit]


class FakeAgentRunService:
    def __init__(self, work: FakeWorkStore | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.work = work

    async def assign_and_run(
        self, ctx, *, work_id, agent_id, playbook_name=None,
        playbook_version=None, model=None, provider=None,
    ) -> dict[str, Any]:
        run_id = uuid4()
        self.calls.append({
            "work_id": work_id, "agent_id": agent_id,
            "playbook_name": playbook_name, "run_id": run_id,
        })
        # Mirror the real service: the work item now shows the agent as assignee
        # (so a later stage that omits `agent` can fall back to it).
        if self.work is not None:
            item = self.work.items.setdefault(str(work_id), {"id": work_id})
            item["assignee_type"] = "agent"
            item["assignee_id"] = agent_id
        return {"id": run_id, "work_item_id": work_id, "agent_id": agent_id}


class FakeProcedural:
    def __init__(self, tool_recipe: dict[str, Any]) -> None:
        self._recipe = tool_recipe

    async def get_procedure(self, org_id, name, version=None):
        return {"name": name, "version": version or 1, "tool_recipe": self._recipe}


def _orchestrator(tool_recipe, items=None):
    runs = FakeWorkflowRunStore()
    work = FakeWorkStore(items)
    agent_runs = FakeAgentRunService(work)
    procedural = FakeProcedural(tool_recipe)
    orch = WorkflowOrchestrator(
        runs=runs, work=work, procedural=procedural, agent_runs=agent_runs,
    )
    return orch, runs, work, agent_runs


def _running_agent_step(runs: FakeWorkflowRunStore, work_id: UUID) -> dict[str, Any]:
    for step in runs.steps.values():
        if (
            str(step["work_item_id"]) == str(work_id)
            and step["owner"] == "agent"
            and step["status"] == "running"
        ):
            return step
    raise AssertionError("no running agent step for work item")


def _waiting_human_step(runs: FakeWorkflowRunStore, work_id: UUID) -> dict[str, Any]:
    for step in runs.steps.values():
        if (
            str(step["work_item_id"]) == str(work_id)
            and step["owner"] == "human"
            and step["status"] == "waiting_human"
        ):
            return step
    raise AssertionError("no waiting-human step for work item")


_PIPELINE = {
    "stages": [
        {"id": "triage", "owner": "agent", "agent": "cursor",
         "playbook": "triage-pb", "advance": "auto", "on_done": "implement"},
        {"id": "implement", "owner": "agent", "playbook": "ship-pr",
         "advance": "auto", "on_done": "review"},
        {"id": "review", "owner": "human", "advance": "manual",
         "on_approve": "done", "on_reject": "implement"},
    ]
}


async def test_pipeline_agent_stages_then_human_gate_to_done() -> None:
    work_id = uuid4()
    orch, runs, work, agent_runs = _orchestrator(
        _PIPELINE, items={str(work_id): {"id": work_id}}
    )
    ctx = _ctx()

    run = await orch.start(ctx, workflow_name="wf", work_ids=[work_id])
    assert run["status"] == "running"
    assert run["work_item_count"] == 1
    # First agent stage dispatched.
    assert len(agent_runs.calls) == 1
    assert agent_runs.calls[0]["playbook_name"] == "triage-pb"

    # triage completes -> auto-advance to implement (second dispatch).
    step1 = _running_agent_step(runs, work_id)
    await orch.on_step_complete(ctx, agent_run_id=step1["agent_run_id"], success=True)
    assert len(agent_runs.calls) == 2
    assert agent_runs.calls[1]["playbook_name"] == "ship-pr"

    # implement completes -> human gate opens; run still running.
    step2 = _running_agent_step(runs, work_id)
    await orch.on_step_complete(ctx, agent_run_id=step2["agent_run_id"], success=True)
    gate = _waiting_human_step(runs, work_id)
    assert gate["stage_id"] == "review"
    run_now = await runs.get_run(ORG, run["id"])
    assert run_now["status"] == "running"

    # Human approves -> item closes done, run completes.
    await orch.advance(ctx, step_id=gate["id"], decision="approve")
    assert work.items[str(work_id)]["work_status"] == "done"
    run_done = await runs.get_run(ORG, run["id"])
    assert run_done["status"] == "completed"


async def test_human_reject_loops_back_to_earlier_stage() -> None:
    work_id = uuid4()
    orch, runs, work, agent_runs = _orchestrator(
        _PIPELINE, items={str(work_id): {"id": work_id}}
    )
    ctx = _ctx()
    await orch.start(ctx, workflow_name="wf", work_ids=[work_id])

    # Drive to the human gate.
    await orch.on_step_complete(
        ctx, agent_run_id=_running_agent_step(runs, work_id)["agent_run_id"], success=True
    )
    await orch.on_step_complete(
        ctx, agent_run_id=_running_agent_step(runs, work_id)["agent_run_id"], success=True
    )
    gate = _waiting_human_step(runs, work_id)
    dispatches_before = len(agent_runs.calls)

    # Reject -> route back to implement -> a fresh agent dispatch, iteration bumped.
    run = await orch.advance(ctx, step_id=gate["id"], decision="reject")
    assert len(agent_runs.calls) == dispatches_before + 1
    assert agent_runs.calls[-1]["playbook_name"] == "ship-pr"
    assert run["iteration"] == 1
    assert work.items[str(work_id)].get("work_status") != "done"


async def test_max_iterations_closes_item() -> None:
    recipe = {
        "stages": [
            {"id": "work", "owner": "agent", "agent": "cursor", "advance": "auto",
             "on_done": "gate"},
            {"id": "gate", "owner": "human", "advance": "manual",
             "on_approve": "done", "on_reject": "work"},
        ],
        "loop": {"select": {}, "until": "all_terminal", "max_iterations": 2},
    }
    work_id = uuid4()
    orch, runs, work, _agent_runs = _orchestrator(
        recipe, items={str(work_id): {"id": work_id}}
    )
    ctx = _ctx()
    await orch.start(ctx, workflow_name="wf", work_ids=[work_id])

    # Reject twice; the second reject hits the iteration cap and closes the item.
    for _ in range(2):
        await orch.on_step_complete(
            ctx, agent_run_id=_running_agent_step(runs, work_id)["agent_run_id"],
            success=True,
        )
        gate = _waiting_human_step(runs, work_id)
        await orch.advance(ctx, step_id=gate["id"], decision="reject")

    assert work.items[str(work_id)]["work_status"] == "done"
    run_done = await runs.get_run(ORG, run_id=next(iter(runs.runs)))
    assert run_done["status"] == "completed"


async def test_manual_agent_stage_opens_human_gate() -> None:
    recipe = {
        "stages": [
            {"id": "build", "owner": "agent", "agent": "cursor", "advance": "manual",
             "on_done": "done"},
        ]
    }
    work_id = uuid4()
    orch, runs, work, _agent_runs = _orchestrator(
        recipe, items={str(work_id): {"id": work_id}}
    )
    ctx = _ctx()
    await orch.start(ctx, workflow_name="wf", work_ids=[work_id])

    # Agent runs, then a human gate is opened (manual advance) at the same stage.
    await orch.on_step_complete(
        ctx, agent_run_id=_running_agent_step(runs, work_id)["agent_run_id"], success=True
    )
    gate = _waiting_human_step(runs, work_id)
    assert gate["stage_id"] == "build"

    await orch.advance(ctx, step_id=gate["id"], decision="approve")
    assert work.items[str(work_id)]["work_status"] == "done"


async def test_start_uses_selector_when_no_work_ids() -> None:
    a, b = uuid4(), uuid4()
    items = {
        str(a): {"id": a, "work_status": "todo"},
        str(b): {"id": b, "work_status": "done"},  # filtered out
    }
    orch, _runs, _work, agent_runs = _orchestrator(
        {"stages": [{"id": "s", "owner": "agent", "agent": "cursor", "advance": "auto",
                     "on_done": "done"}],
         "loop": {"select": {"work_status": "todo"}, "max_iterations": 5}},
        items=items,
    )
    ctx = _ctx()
    run = await orch.start(ctx, workflow_name="wf")
    assert run["work_item_count"] == 1
    assert agent_runs.calls[0]["work_id"] == a


async def test_no_items_completes_immediately() -> None:
    orch, _runs, _work, agent_runs = _orchestrator(
        {"stages": [{"id": "s", "owner": "agent", "agent": "cursor", "advance": "auto"}]},
    )
    ctx = _ctx()
    run = await orch.start(ctx, workflow_name="wf", work_ids=[])
    assert run["status"] == "completed"
    assert agent_runs.calls == []


async def test_start_rejects_bad_definition() -> None:
    orch, _runs, _work, _agent = _orchestrator({"stages": []})
    ctx = _ctx()
    with pytest.raises(WorkflowError):
        await orch.start(ctx, workflow_name="wf", work_ids=[uuid4()])


async def test_on_step_complete_is_noop_for_unknown_run() -> None:
    orch, _runs, _work, agent_runs = _orchestrator(_PIPELINE)
    ctx = _ctx()
    # No step references this agent-run id -> safe no-op.
    await orch.on_step_complete(ctx, agent_run_id=uuid4(), success=True)
    assert agent_runs.calls == []


# --- definition validation -------------------------------------------------


def test_parse_definition_rejects_unknown_routing_target() -> None:
    with pytest.raises(WorkflowDefinitionError):
        parse_definition({"stages": [
            {"id": "a", "owner": "agent", "on_done": "nowhere"},
        ]})


def test_parse_definition_rejects_duplicate_stage_ids() -> None:
    with pytest.raises(WorkflowDefinitionError):
        parse_definition({"stages": [
            {"id": "a", "owner": "agent"}, {"id": "a", "owner": "agent"},
        ]})


def test_parse_definition_defaults_advance_by_owner() -> None:
    d = parse_definition({"stages": [
        {"id": "a", "owner": "agent", "on_done": "b"},
        {"id": "b", "owner": "human", "on_approve": "done"},
    ]})
    assert d.stage("a").advance == "auto"
    assert d.stage("b").advance == "manual"
    assert d.first.id == "a"


def test_parse_definition_accepts_terminal_targets() -> None:
    d = parse_definition({"stages": [
        {"id": "a", "owner": "agent", "on_done": "done"},
    ]})
    assert d.stage("a").next_target("done") == "done"
