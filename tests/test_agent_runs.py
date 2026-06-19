"""Unit tests for background agent runs (mocked stores -- no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from teamshared.agents.runner import AgentRunner
from teamshared.agents.service import AGENT_RUN_STREAM, AgentRunService
from teamshared.config import Settings
from teamshared.identity.principal import Principal
from teamshared.memory.request_context import RequestContext

ORG = UUID("00000000-0000-0000-0000-000000000001")
WORK_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
AGENT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
RUN_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def _ctx() -> RequestContext:
    principal = Principal(
        org_id=ORG, type="user", id=uuid4(), display="alice@example.com",
        roles=("org_admin",),
    )
    authorizer = MagicMock()
    authorizer.require = AsyncMock()
    return RequestContext(principal=principal, db=MagicMock(), authorizer=authorizer)


def _service() -> tuple[AgentRunService, MagicMock, MagicMock, MagicMock]:
    runs = MagicMock()
    runs.create = AsyncMock(
        return_value={"id": RUN_ID, "work_item_id": WORK_ID, "agent_id": AGENT_ID}
    )
    runs.append_trace = AsyncMock()
    runs.request_cancel = AsyncMock(
        return_value={"id": RUN_ID, "work_item_id": WORK_ID}
    )
    runs.get = AsyncMock(
        return_value={
            "id": RUN_ID, "work_item_id": WORK_ID, "agent_id": AGENT_ID,
            "playbook_name": "ship-pr", "playbook_version": 2,
            "model": "gpt-4o-mini", "provider": "openrouter",
        }
    )
    work = MagicMock()
    work.get = AsyncMock(return_value={"id": WORK_ID, "title": "Ship it"})
    work.get_agent = AsyncMock(
        return_value={"id": AGENT_ID, "name": "bot", "runtime": "cloud"}
    )
    work.update = AsyncMock()
    work.add_comment = AsyncMock()
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value="1-0")
    return AgentRunService(runs, work, queue), runs, work, queue


async def test_assign_and_run_creates_queues_and_records() -> None:
    svc, runs, work, queue = _service()
    ctx = _ctx()

    run = await svc.assign_and_run(
        ctx, work_id=WORK_ID, agent_id=AGENT_ID,
        playbook_name="ship-pr", playbook_version=2, model="gpt-4o-mini",
    )

    assert run["id"] == RUN_ID
    runs.create.assert_awaited_once()
    # The work item now shows the agent as assignee.
    work.update.assert_awaited_once()
    _, kwargs = work.update.call_args
    assert kwargs["fields"]["assignee_type"] == "agent"
    assert kwargs["fields"]["assignee_id"] == AGENT_ID
    # Enqueued exactly once, deduped by run id.
    queue.enqueue.assert_awaited_once()
    args, kwargs = queue.enqueue.call_args
    assert args[0] == AGENT_RUN_STREAM
    assert kwargs["idempotency_key"] == str(RUN_ID)
    assert args[1]["run_id"] == str(RUN_ID)
    # Timeline events: a queued trace + a work comment.
    runs.append_trace.assert_awaited()
    work.add_comment.assert_awaited()


async def test_assign_and_run_requires_permission() -> None:
    svc, _runs, _work, _queue = _service()
    ctx = _ctx()
    await svc.assign_and_run(ctx, work_id=WORK_ID, agent_id=AGENT_ID)
    ctx.authorizer.require.assert_awaited()  # type: ignore[attr-defined]


async def test_assign_and_run_rejects_user_agent() -> None:
    from teamshared.agents.service import AgentNotRunnableError

    svc, _runs, work, queue = _service()
    work.get_agent = AsyncMock(
        return_value={"id": AGENT_ID, "name": "cursor", "runtime": "user"}
    )
    ctx = _ctx()
    with pytest.raises(AgentNotRunnableError):
        await svc.assign_and_run(ctx, work_id=WORK_ID, agent_id=AGENT_ID)
    queue.enqueue.assert_not_awaited()


async def test_assign_user_agent_assigns_without_running() -> None:
    svc, runs, work, queue = _service()
    work.get_agent = AsyncMock(
        return_value={"id": AGENT_ID, "name": "cursor", "runtime": "user"}
    )
    ctx = _ctx()
    result = await svc.assign(ctx, work_id=WORK_ID, agent_id=AGENT_ID)
    assert result == {"assigned": True, "runtime": "user", "run": None}
    work.update.assert_awaited_once()
    runs.create.assert_not_awaited()
    queue.enqueue.assert_not_awaited()
    work.add_comment.assert_awaited()


async def test_assign_cloud_agent_queues_run() -> None:
    svc, runs, _work, queue = _service()
    ctx = _ctx()
    result = await svc.assign(ctx, work_id=WORK_ID, agent_id=AGENT_ID)
    assert result["assigned"] is True
    assert result["runtime"] == "cloud"
    runs.create.assert_awaited_once()
    queue.enqueue.assert_awaited_once()


async def test_maybe_autorun_skips_user_agent() -> None:
    svc, runs, work, queue = _service()
    work.get_agent = AsyncMock(
        return_value={"id": AGENT_ID, "name": "cursor", "runtime": "user"}
    )
    ctx = _ctx()
    out = await svc.maybe_autorun_on_assign(ctx, work_id=WORK_ID, agent_id=AGENT_ID)
    assert out is None
    runs.create.assert_not_awaited()
    queue.enqueue.assert_not_awaited()


async def test_maybe_autorun_runs_cloud_agent() -> None:
    svc, runs, _work, queue = _service()
    ctx = _ctx()
    out = await svc.maybe_autorun_on_assign(ctx, work_id=WORK_ID, agent_id=AGENT_ID)
    assert out is not None
    runs.create.assert_awaited_once()
    queue.enqueue.assert_awaited_once()


async def test_cancel_flags_and_comments() -> None:
    svc, runs, work, _queue = _service()
    ctx = _ctx()
    await svc.cancel(ctx, RUN_ID)
    runs.request_cancel.assert_awaited_once_with(ORG, RUN_ID)
    work.add_comment.assert_awaited()


async def test_retry_clones_previous_run() -> None:
    svc, runs, _work, queue = _service()
    ctx = _ctx()
    await svc.retry(ctx, RUN_ID)
    runs.get.assert_awaited_once_with(ORG, RUN_ID)
    # Retry goes through assign_and_run -> a fresh enqueue.
    queue.enqueue.assert_awaited()


# --- runner ----------------------------------------------------------------


def _runner(monkeypatch: pytest.MonkeyPatch, *, output: str, playbook: dict | None):
    runs = MagicMock()
    runs.db = MagicMock()
    runs.append_trace = AsyncMock()
    runs.is_cancel_requested = AsyncMock(return_value=False)
    runs.record_model_call = AsyncMock()
    runs.mark = AsyncMock()

    authorizer = MagicMock()
    authorizer.require = AsyncMock()
    facade = MagicMock()
    facade.services.authorizer.return_value = authorizer

    work = MagicMock()
    work.get = AsyncMock(
        return_value={
            "id": WORK_ID, "title": "Investigate flake", "description_md": "It flakes.",
            "repo": None, "github": None,
        }
    )
    work.list_comments = AsyncMock(return_value=[])
    work.add_comment = AsyncMock()

    procedural = MagicMock()
    procedural.get_procedure = AsyncMock(return_value=playbook)

    ingestion = MagicMock()
    ingestion.ingest = AsyncMock()

    runner = AgentRunner(
        settings=Settings(_env_file=None),
        runs=runs, facade=facade, work=work,
        procedural=procedural, skills=MagicMock(), ingestion=ingestion,
    )

    async def _fake_principal(org_id, agent_id):
        return Principal(org_id=org_id, type="agent", id=agent_id, display="cursor",
                         roles=("agent",))

    monkeypatch.setattr(runner, "_agent_principal", _fake_principal)
    runner.assembler = MagicMock()
    runner.assembler.assemble = AsyncMock(
        return_value=SimpleNamespace(
            rendered="## Semantic\n- a prior fact",
            tokens_used=12, counts_by_pillar={"semantic": 1},
        )
    )

    monkeypatch.setattr(
        "teamshared.agents.runner.load_teamshared_memory_rule_mdc",
        lambda: "RULE-MARKER: TeamShared operating rules body",
    )

    captured: dict = {}

    class _FakeClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        async def _create(self, *, model, messages, temperature):
            captured["model"] = model
            captured["messages"] = messages
            return SimpleNamespace(
                id="req-123",
                choices=[SimpleNamespace(message=SimpleNamespace(content=output))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
            )

    monkeypatch.setattr(
        "teamshared.agents.runner.build_chat_client", lambda settings: _FakeClient()
    )
    return runner, runs, work, ingestion, captured


def _run_row() -> dict:
    return {
        "id": str(RUN_ID), "org_id": str(ORG), "work_item_id": str(WORK_ID),
        "agent_id": str(AGENT_ID), "model": "gpt-4o-mini", "provider": "openrouter",
        "playbook_name": "ship-pr", "playbook_version": 2, "lease_owner": "w1",
    }


async def test_runner_includes_rule_and_playbook_then_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playbook = {"name": "ship-pr", "version": 2, "steps_md": "PLAYBOOK-STEPS: do x"}
    runner, runs, work, ingestion, captured = _runner(
        monkeypatch, output="Did the thing. Findings: none.", playbook=playbook,
    )

    await runner.execute(_run_row())

    system = captured["messages"][0]["content"]
    user = captured["messages"][1]["content"]
    assert "RULE-MARKER" in system  # canonical teamshared.mdc rule injected
    assert "PLAYBOOK-STEPS" in system  # selected playbook injected
    assert "UNTRUSTED DATA" in user  # recalled memory fenced as untrusted

    # Model-call metadata persisted (no raw bodies).
    runs.record_model_call.assert_awaited_once()
    _, kwargs = runs.record_model_call.call_args
    assert kwargs["prompt_tokens"] == 100
    assert kwargs["completion_tokens"] == 20

    # Completed + result posted as a work comment.
    mark_statuses = [c.kwargs.get("status") for c in runs.mark.call_args_list]
    assert "completed" in mark_statuses
    work.add_comment.assert_awaited()
    # Durable memory written (the "can write memory" decision).
    ingestion.ingest.assert_awaited()


async def test_runner_does_not_leak_prompt_into_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playbook = {"name": "ship-pr", "version": 2, "steps_md": "SECRET-STEPS"}
    runner, runs, _work, _ingestion, _captured = _runner(
        monkeypatch, output="result", playbook=playbook,
    )
    await runner.execute(_run_row())

    for call in runs.append_trace.call_args_list:
        payload = call.kwargs.get("payload") or {}
        blob = repr(payload)
        assert "RULE-MARKER" not in blob
        assert "SECRET-STEPS" not in blob


async def test_runner_fails_when_playbook_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, runs, _work, _ingestion, _captured = _runner(
        monkeypatch, output="x", playbook=None,
    )
    # A run that names a playbook which resolves to None must fail safely.
    await runner.execute(_run_row())
    mark_statuses = [c.kwargs.get("status") for c in runs.mark.call_args_list]
    assert "failed" in mark_statuses


async def test_runner_honours_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playbook = {"name": "ship-pr", "version": 2, "steps_md": "x"}
    runner, runs, work, _ingestion, _captured = _runner(
        monkeypatch, output="x", playbook=playbook,
    )
    runs.is_cancel_requested = AsyncMock(return_value=True)
    await runner.execute(_run_row())
    mark_statuses = [c.kwargs.get("status") for c in runs.mark.call_args_list]
    assert mark_statuses == ["cancelled"]
    work.add_comment.assert_awaited()


async def test_runner_advances_workflow_on_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed run wired to a workflow auto-advances its item (the hook)."""
    playbook = {"name": "ship-pr", "version": 2, "steps_md": "x"}
    runner, _runs, _work, _ingestion, _captured = _runner(
        monkeypatch, output="done", playbook=playbook,
    )
    orchestrator = MagicMock()
    orchestrator.on_step_complete = AsyncMock()
    runner.orchestrator = orchestrator

    await runner.execute(_run_row())

    orchestrator.on_step_complete.assert_awaited_once()
    _, kwargs = orchestrator.on_step_complete.call_args
    assert kwargs["success"] is True
    assert kwargs["agent_run_id"] == RUN_ID
