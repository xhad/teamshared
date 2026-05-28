"""End-to-end tool smoke test using FastMCP's in-memory client.

Memory backends are mocked so this runs without Postgres/Redis/Mem0. The goal
is to assert that:

- Every tool is registered and reachable.
- Tool signatures accept the argument shapes the plan documents.
- Identity resolution falls through to "anonymous" when no token is bound.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, FastMCP

from teamshared.memory.types import RecallResult
from teamshared.server.state import ServerState, clear_state, set_state
from teamshared.server.tools import register_tools


@pytest.fixture
def mcp_with_mocks() -> tuple[FastMCP, ServerState]:
    mcp = FastMCP(name="teamshared-test")
    register_tools(mcp)

    working = MagicMock()
    working.open_session = AsyncMock(return_value="sess_abc")
    working.append_turn = AsyncMock(return_value=1)
    working.close_session = AsyncMock(
        return_value={"session_id": "sess_abc", "turn_count": 1, "closed_at": "now", "distill_enqueued": True}
    )
    working.recent_records = AsyncMock(return_value=[])
    working.client = MagicMock()
    working.client.ping = AsyncMock(return_value=True)

    semantic = MagicMock()
    semantic.add = AsyncMock(
        return_value=[{"id": "m1", "memory": "stored", "metadata": {"pillar": "semantic"}}]
    )
    semantic.list_episodes = AsyncMock(return_value=[])
    semantic.delete = AsyncMock(return_value=True)
    semantic._memory = object()  # so /health says ok

    procedural = MagicMock()
    procedural.get_procedure = AsyncMock(return_value=None)
    procedural.set_procedure = AsyncMock(
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
        }
    )
    procedural.list_procedures = AsyncMock(return_value=[])
    procedural.pool = MagicMock()
    pool_ctx = MagicMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=pool_ctx)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool_ctx.cursor = MagicMock(return_value=pool_ctx)
    pool_ctx.execute = AsyncMock()
    pool_ctx.fetchone = AsyncMock(return_value=(1,))
    procedural.pool.connection = MagicMock(return_value=pool_ctx)

    recall = MagicMock()
    recall.search = AsyncMock(
        return_value=RecallResult(query="q", records=[], counts_by_pillar={"semantic": 0})
    )

    agent_state = MagicMock()
    agent_state.get = AsyncMock(return_value=None)
    agent_state.set = AsyncMock()

    state = ServerState(
        settings=MagicMock(),
        tokens=MagicMock(),
        invites=MagicMock(),
        working=working,
        agent_state=agent_state,
        semantic_episodic=semantic,
        procedural=procedural,
        recall=recall,
        graph=None,
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
    assert data["components"]["redis"] == "ok"
    assert data["components"]["mem0"] == "ok"


async def test_memory_remember_calls_semantic_add(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    data = await _call(mcp, "memory_remember", content="user likes dark mode", kind="preference")
    assert data["pillar"] == "semantic"
    assert data["count"] == 1
    state.semantic_episodic.add.assert_awaited_once()


async def test_memory_remember_event_routes_episodic(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    data = await _call(mcp, "memory_remember", content="rolled out feature x", kind="event")
    assert data["pillar"] == "episodic"
    assert state.semantic_episodic.add.await_args.kwargs["pillar"] == "episodic"


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
    assert state.working.close_session.await_args.kwargs["distill"] is False


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
    """The shared brain is the default: durable pillars are not filtered to
    the caller. This pins the contract so we don't silently regress to the
    old "default to caller's identity" behavior, which made cross-agent
    visibility impossible without an explicit override.
    """
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_recall", query="anything")
    state.recall.search.assert_awaited_once()
    kwargs = state.recall.search.await_args.kwargs
    assert kwargs["agent"] is None, (
        "memory_recall must default to agent=None (shared brain); see AGENTS.md"
    )


async def test_memory_recall_passes_explicit_agent_filter(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_recall", query="anything", agent="cursor")
    kwargs = state.recall.search.await_args.kwargs
    assert kwargs["agent"] == "cursor"


async def test_memory_episodes_list_is_unscoped_by_default(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_episodes_list", limit=5)
    state.semantic_episodic.list_episodes.assert_awaited_once()
    kwargs = state.semantic_episodic.list_episodes.await_args.kwargs
    assert kwargs["agent"] is None


async def test_memory_episodes_list_passes_explicit_agent_filter(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    mcp, state = mcp_with_mocks
    await _call(mcp, "memory_episodes_list", limit=5, agent="hermes")
    kwargs = state.semantic_episodic.list_episodes.await_args.kwargs
    assert kwargs["agent"] == "hermes"


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
        mcp,
        "memory_procedure_set",
        name="p1",
        steps_md="do thing",
        description="x",
    )
    assert stored["version"] == 1
    state.procedural.set_procedure.assert_awaited_once()

    # get returns None from the mock
    state.procedural.get_procedure.return_value = None
    result = await _call(mcp, "memory_procedure_get", name="p1")
    assert result is None or result == {}


async def test_memory_state_get_and_set(
    mcp_with_mocks: tuple[FastMCP, ServerState],
) -> None:
    from teamshared.auth import AgentIdentity, _current_agent

    mcp, state = mcp_with_mocks
    token = _current_agent.set(AgentIdentity(agent="cursor", token_prefix="teamshared_test"))
    try:
        payload = {"version": 1, "turnsSinceLastRun": 3}
        state.agent_state.get.return_value = payload
        got = await _call(
            mcp,
            "memory_state_get",
            repo="Users-chad-code-sapien-teamshared",
            key="continual-learning/cadence",
        )
        assert got["value"] == payload
        state.agent_state.get.assert_awaited_once_with(
            "teamshared_test",
            "Users-chad-code-sapien-teamshared",
            "continual-learning/cadence",
        )

        stored = await _call(
            mcp,
            "memory_state_set",
            repo="Users-chad-code-sapien-teamshared",
            key="continual-learning/cadence",
            value={"version": 1, "turnsSinceLastRun": 0},
        )
        assert stored["stored"] is True
        state.agent_state.set.assert_awaited_once()
    finally:
        _current_agent.reset(token)
