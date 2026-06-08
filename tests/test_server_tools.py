"""End-to-end tool smoke test using FastMCP's in-memory client.

Post-G2 the tools are thin shells over :class:`MemoryFacade`, which is mocked
here so this runs without Postgres/Redis. The goal is to assert that:

- Every tool is registered and reachable.
- Tools resolve a Principal and delegate to the facade with the documented
  argument shapes.
- The shared-brain contract holds: recall/episodes default to ``agent_filter``
  ``None`` and pass an explicit ``agent=`` straight through (see AGENTS.md).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, FastMCP

from teamshared.identity.principal import Principal
from teamshared.memory.types import RecallResult
from teamshared.server.state import ServerState, clear_state, set_state
from teamshared.server.tools import register_tools

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _AsyncCM:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    async def __aenter__(self) -> object:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def mcp_with_mocks() -> tuple[FastMCP, ServerState]:
    mcp = FastMCP(name="teamshared-test")
    register_tools(mcp)

    working = MagicMock()
    working.client = MagicMock()
    working.client.ping = AsyncMock(return_value=True)
    working.last_heartbeat = AsyncMock(return_value="2026-01-01T00:00:00+00:00")
    working.queue_stats = AsyncMock(
        return_value={
            "distill_queue": 0,
            "distill_dead": 0,
            "curate_queue": 0,
            "curate_dead": 0,
            "curate_pending": 0,
        }
    )

    # services + tenant_db.admin() for the health probe.
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchone = AsyncMock(return_value=(1,))
    services = MagicMock()
    services.tenant_db.admin = MagicMock(return_value=_AsyncCM(conn))
    services.vector_store.health = AsyncMock(return_value="text-embedding-3-small")

    facade = MagicMock()
    facade.resolver.anonymous = AsyncMock(
        return_value=Principal(org_id=ORG, type="agent", id=uuid.uuid4(), display="anonymous")
    )
    facade.remember = AsyncMock(
        return_value={"agent": "anonymous", "pillar": "semantic", "memory_id": "m1", "status": "active"}
    )
    facade.recall = AsyncMock(
        return_value=RecallResult(query="q", records=[], counts_by_pillar={"semantic": 0})
    )
    facade.episodes_list = AsyncMock(return_value={"count": 0, "episodes": []})
    facade.session_open = AsyncMock(return_value={"session_id": "sess_abc", "agent": "anonymous"})
    facade.session_append = AsyncMock(return_value={"turn_count": 1})
    facade.session_close = AsyncMock(
        return_value={"session_id": "sess_abc", "turn_count": 1, "closed_at": "now",
                      "distill_enqueued": False}
    )
    facade.procedure_set = AsyncMock(
        return_value={
            "id": 1,
            "name": "p1",
            "version": 1,
            "description": "x",
            "steps_md": "do thing",
            "tool_recipe": None,
            "tags": [],
            "created_by": "anonymous",
            "created_at": None,
            "status": "active",
        }
    )
    facade.procedure_get = AsyncMock(return_value=None)
    facade.procedures_list = AsyncMock(return_value={"count": 0, "procedures": []})
    facade.strategic_statement_get = AsyncMock(return_value=None)
    facade.strategic_statement_set = AsyncMock(
        return_value={"kind": "vision", "status": "pending_approval", "id": "s1"}
    )
    facade.strategic_plan_list = AsyncMock(return_value={"count": 0, "plans": []})
    facade.graph_relate = AsyncMock(return_value={"ok": False, "reason": "graph_disabled"})
    facade.graph_related = AsyncMock(return_value={"records": [], "reason": "graph_disabled"})
    facade.forget = AsyncMock(return_value={"memory_id": "m1", "deleted": True})
    facade.state_get = AsyncMock(return_value={"repo": "r", "key": "k", "value": None})
    facade.state_set = AsyncMock(return_value={"repo": "r", "key": "k", "stored": True})
    facade.work_list = AsyncMock(return_value={"count": 0, "items": []})
    facade.work_get = AsyncMock(return_value=None)
    facade.work_create = AsyncMock(return_value={"id": "w1", "title": "t", "approval_status": "active"})
    facade.work_update = AsyncMock(return_value={"id": "w1", "work_status": "in_progress"})
    facade.work_close = AsyncMock(return_value={"id": "w1", "work_status": "done"})
    facade.work_comment_add = AsyncMock(return_value={"id": "c1", "body_md": "note"})
    facade.work_comment_list = AsyncMock(return_value={"count": 0, "comments": []})

    settings = MagicMock()
    settings.embed_provider = "openai"
    settings.llm_provider = "openai"
    settings.queue_depth_warn_threshold = 100
    settings.queue_depth_critical_threshold = 500

    graph = MagicMock()
    graph.verify = AsyncMock(return_value=None)

    state = ServerState(
        settings=settings,
        invites=MagicMock(),
        working=working,
        agent_state=MagicMock(),
        procedural=MagicMock(),
        services=services,
        facade=facade,
        audit=MagicMock(),
        graph=graph,
    )
    set_state(state)
    yield mcp, state
    clear_state()


async def _call(mcp: FastMCP, tool: str, **kwargs: Any) -> Any:
    async with Client(mcp) as client:
        result = await client.call_tool(tool, kwargs)
        return result.data if hasattr(result, "data") else result


async def test_health_tool(mcp_with_mocks: tuple[FastMCP, ServerState]) -> None:
    mcp, _ = mcp_with_mocks
    data = await _call(mcp, "health")
    assert data["status"] == "ok"
    assert "version" in data
    comps = data["components"]
    assert comps["server"] == "ok"
    assert comps["redis"] == "ok"
    assert comps["postgres"] == "ok"
    assert comps["semantic"] == "ok (text-embedding-3-small)"
    assert comps["distiller"] == "ok"
    assert comps["graph"] == "ok"
    # Ollama is unused in the mock (openai providers); "disabled" must not degrade.
    assert comps["ollama"] == "disabled"


async def test_version_tool_reports_update_when_behind(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, _ = mcp_with_mocks
    data = await _call(mcp, "version", installed_rule_version="0.0.1")
    assert data["server_version"]
    assert data["rule_version"]
    assert data["installed_rule_version"] == "0.0.1"
    assert data["update_available"] is True
    # Behind ⇒ the full canonical rule markdown is returned for rewriting.
    assert "# teamshared Memory Protocol" in data["rule_markdown"]
    assert data["rule_path"].endswith("teamshared.mdc")


async def test_version_tool_no_update_when_current(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, _ = mcp_with_mocks
    current = await _call(mcp, "version")  # no installed version ⇒ update_available
    assert current["update_available"] is True  # unknown installed ⇒ update
    data = await _call(mcp, "version", installed_rule_version=current["rule_version"])
    assert data["update_available"] is False
    assert "rule_markdown" not in data


async def test_memory_remember_delegates_to_facade(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    data = await _call(mcp, "memory_remember", content="user likes dark mode", kind="preference")
    assert data["pillar"] == "semantic"
    state.facade.remember.assert_awaited_once()
    assert state.facade.remember.await_args.kwargs["kind"] == "preference"


async def test_memory_remember_passes_repo_and_github(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(
        mcp,
        "memory_remember",
        content="deploy uses railtail",
        kind="fact",
        repo="home-chad-code-teamshared",
        github="xhad/teamshared",
    )
    kwargs = state.facade.remember.await_args.kwargs
    assert kwargs["repo"] == "home-chad-code-teamshared"
    assert kwargs["github"] == "xhad/teamshared"


async def test_memory_recall_passes_repo_and_github(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(
        mcp,
        "memory_recall",
        query="deploy",
        repo="home-chad-code-teamshared",
        github="xhad/teamshared",
    )
    kwargs = state.facade.recall.await_args.kwargs
    assert kwargs["repo"] == "home-chad-code-teamshared"
    assert kwargs["github"] == "xhad/teamshared"


async def test_memory_remember_rejects_procedure_kind(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, _ = mcp_with_mocks
    from fastmcp.exceptions import ToolError

    with pytest.raises((ToolError, ValueError)):
        await _call(mcp, "memory_remember", content="x", kind="procedure")


async def test_memory_session_lifecycle(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    opened = await _call(mcp, "memory_session_open", topic="memory plan")
    assert opened["session_id"] == "sess_abc"
    appended = await _call(
        mcp, "memory_session_append", session_id="sess_abc", role="user", content="hi"
    )
    assert appended["turn_count"] == 1
    closed = await _call(mcp, "memory_session_close", session_id="sess_abc", distill=False)
    assert closed["session_id"] == "sess_abc"
    assert state.facade.session_close.await_args.kwargs["distill"] is False


async def test_memory_recall_returns_result_shape(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, _ = mcp_with_mocks
    data = await _call(mcp, "memory_recall", query="dark mode", k=4)
    assert data["query"] == "q"
    assert data["records"] == []
    assert "semantic" in data["counts_by_pillar"]


async def test_memory_recall_is_unscoped_by_default(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    """Shared brain default: durable pillars are not filtered to the caller."""
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_recall", query="anything")
    state.facade.recall.assert_awaited_once()
    assert state.facade.recall.await_args.kwargs["agent_filter"] is None, (
        "memory_recall must default to agent_filter=None (shared brain); see AGENTS.md"
    )


async def test_memory_recall_passes_explicit_agent_filter(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_recall", query="anything", agent="cursor")
    assert state.facade.recall.await_args.kwargs["agent_filter"] == "cursor"


async def test_memory_episodes_list_is_unscoped_by_default(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_episodes_list", limit=5)
    state.facade.episodes_list.assert_awaited_once()
    assert state.facade.episodes_list.await_args.kwargs["agent_filter"] is None


async def test_memory_episodes_list_passes_explicit_agent_filter(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_episodes_list", limit=5, agent="hermes")
    assert state.facade.episodes_list.await_args.kwargs["agent_filter"] == "hermes"


async def test_memory_graph_tools_noop_when_disabled(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, _ = mcp_with_mocks
    related = await _call(mcp, "memory_graph_related", name="user")
    assert related["records"] == []
    assert related["reason"] == "graph_disabled"

    relate = await _call(mcp, "memory_graph_relate", subject="a", predicate="r", object="b")
    assert relate["ok"] is False
    assert relate["reason"] == "graph_disabled"


async def test_memory_procedure_set_and_get(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    stored = await _call(
        mcp, "memory_procedure_set", name="p1", steps_md="do thing", description="x"
    )
    assert stored["version"] == 1
    state.facade.procedure_set.assert_awaited_once()

    result = await _call(mcp, "memory_procedure_get", name="p1")
    assert result is None or result == {}


async def test_memory_strategic_statement_get(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_strategic_statement_get", kind="mission")
    state.facade.strategic_statement_get.assert_awaited_once()


async def test_work_list_and_create(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "work_list", mine=True, limit=10)
    state.facade.work_list.assert_awaited_once()
    created = await _call(mcp, "work_create", title="Test task", work_status="todo")
    assert created["id"] == "w1"
    state.facade.work_create.assert_awaited_once()


async def test_work_comment_tools(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "work_comment_add", work_id="w1", body="Shipped it")
    state.facade.work_comment_add.assert_awaited_once()
    await _call(mcp, "work_comment_list", work_id="w1")
    state.facade.work_comment_list.assert_awaited_once()


async def test_memory_state_get_and_set(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    from teamshared.auth import AgentIdentity, _current_agent

    mcp, state = mcp_with_mocks
    token = _current_agent.set(AgentIdentity(agent="cursor", state_id="teamshared_test"))
    try:
        await _call(
            mcp,
            "memory_state_get",
            repo="Users-chad-code-sapien-teamshared",
            key="continual-learning/cadence",
        )
        assert state.facade.state_get.await_args.kwargs["state_id"] == "teamshared_test"

        stored = await _call(
            mcp,
            "memory_state_set",
            repo="Users-chad-code-sapien-teamshared",
            key="continual-learning/cadence",
            value={"version": 1, "turnsSinceLastRun": 0},
        )
        assert stored["stored"] is True
        state.facade.state_set.assert_awaited_once()
    finally:
        _current_agent.reset(token)
