"""Tests for the tool-call capture middleware."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace

import fakeredis.aioredis
import mcp.types as mt
import pytest
import pytest_asyncio

from teamshared import auth
from teamshared.auth import AgentIdentity
from teamshared.identity.principal import Principal
from teamshared.memory import working as working_mod
from teamshared.memory.working import WorkingMemory
from teamshared.server import capture as capture_mod
from teamshared.server.capture import (
    MAX_TURN_CONTENT_CHARS,
    ToolCallCaptureMiddleware,
    _build_turn,
    _summarize_arguments,
    ingest_turns,
)

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def memory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[WorkingMemory]:
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(working_mod.redis, "from_url", lambda url, **kw: fake)
    mem = WorkingMemory("redis://fake", default_ttl=60)
    await mem.connect()
    try:
        yield mem
    finally:
        await mem.close()


def _state(memory: WorkingMemory) -> SimpleNamespace:
    """Fake ServerState — capture is now gated only by settings.capture_enabled."""
    return SimpleNamespace(working=memory, services=SimpleNamespace())


@dataclass
class _Ctx:
    message: mt.CallToolRequestParams


def _ctx(name: str, arguments: dict | None = None) -> _Ctx:
    return _Ctx(message=mt.CallToolRequestParams(name=name, arguments=arguments))


def _bind(agent: str) -> tuple[object, object]:
    """Bind both the legacy AgentIdentity and an org-scoped Principal."""
    t1 = auth._current_agent.set(AgentIdentity(agent=agent, state_id="sid"))
    t2 = auth._current_principal.set(
        Principal(org_id=ORG, type="agent", id=uuid.uuid4(), display=agent, roles=("agent",))
    )
    return t1, t2


def _unbind(tokens: tuple[object, object]) -> None:
    auth._current_agent.reset(tokens[0])  # type: ignore[arg-type]
    auth._current_principal.reset(tokens[1])  # type: ignore[arg-type]


def test_summarize_arguments_drops_agent_and_truncates() -> None:
    summary = _summarize_arguments({"agent": "cursor", "query": "x" * 500})
    assert "agent=" not in summary
    assert summary.startswith("query=")
    assert "\u2026" in summary


def test_build_turn_marks_status() -> None:
    assert _build_turn("memory_recall", {"query": "hi"}, ok=True) == (
        "memory_recall(query=hi) -> ok"
    )
    assert _build_turn("memory_remember", {"content": "x"}, ok=False).endswith("-> error")


async def test_middleware_records_tool_call(
    memory: WorkingMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_mod, "get_state", lambda: _state(memory))
    mw = ToolCallCaptureMiddleware(idle_seconds=1800, max_turns=200)

    async def call_next(ctx: _Ctx) -> str:
        return "result"

    tokens = _bind("cursor")
    try:
        out = await mw.on_call_tool(_ctx("memory_recall", {"query": "hi"}), call_next)
    finally:
        _unbind(tokens)

    assert out == "result"
    sessions = await memory.list_open_sessions(ORG, "cursor", limit=5)
    assert len(sessions) == 1
    turns = await memory.get_turns(ORG, sessions[0]["session_id"])
    assert turns[0]["content"] == "memory_recall(query=hi) -> ok"


async def test_middleware_skips_health(
    memory: WorkingMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_mod, "get_state", lambda: _state(memory))
    mw = ToolCallCaptureMiddleware(idle_seconds=1800, max_turns=200)

    async def call_next(ctx: _Ctx) -> str:
        return "ok"

    tokens = _bind("cursor")
    try:
        await mw.on_call_tool(_ctx("health"), call_next)
    finally:
        _unbind(tokens)

    assert await memory.list_open_sessions(ORG, "cursor", limit=5) == []


async def test_middleware_skips_when_unauthenticated(
    memory: WorkingMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_mod, "get_state", lambda: _state(memory))
    mw = ToolCallCaptureMiddleware(idle_seconds=1800, max_turns=200)

    async def call_next(ctx: _Ctx) -> str:
        return "ok"

    out = await mw.on_call_tool(_ctx("memory_recall", {"query": "hi"}), call_next)
    assert out == "ok"
    assert await memory.list_open_sessions(ORG, "cursor", limit=5) == []


async def test_middleware_capture_failure_does_not_break_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RuntimeError("state down")

    monkeypatch.setattr(capture_mod, "get_state", _boom)
    mw = ToolCallCaptureMiddleware(idle_seconds=1800, max_turns=200)

    async def call_next(ctx: _Ctx) -> str:
        return "still-works"

    tokens = _bind("cursor")
    try:
        out = await mw.on_call_tool(_ctx("memory_recall", {"query": "hi"}), call_next)
    finally:
        _unbind(tokens)
    assert out == "still-works"


async def test_middleware_records_on_tool_error(
    memory: WorkingMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_mod, "get_state", lambda: _state(memory))
    mw = ToolCallCaptureMiddleware(idle_seconds=1800, max_turns=200)

    async def call_next(ctx: _Ctx) -> str:
        raise ValueError("tool blew up")

    tokens = _bind("cursor")
    try:
        with pytest.raises(ValueError, match="tool blew up"):
            await mw.on_call_tool(_ctx("memory_remember", {"content": "x"}), call_next)
    finally:
        _unbind(tokens)

    sessions = await memory.list_open_sessions(ORG, "cursor", limit=5)
    turns = await memory.get_turns(ORG, sessions[0]["session_id"])
    assert turns[0]["content"].endswith("-> error")


async def test_ingest_turns_records_valid_turns(memory: WorkingMemory) -> None:
    recorded = await ingest_turns(
        memory,
        ORG,
        "cursor",
        [
            {"role": "user", "content": "what's in the brain?"},
            {"role": "assistant", "content": "Here's the summary."},
        ],
        idle_seconds=1800,
        max_turns=200,
    )
    assert recorded == 2
    sessions = await memory.list_open_sessions(ORG, "cursor", limit=5)
    turns = await memory.get_turns(ORG, sessions[0]["session_id"])
    assert [t["role"] for t in turns] == ["user", "assistant"]


async def test_ingest_turns_truncates_oversized_content(memory: WorkingMemory) -> None:
    recorded = await ingest_turns(
        memory,
        ORG,
        "cursor",
        [{"role": "user", "content": "x" * (MAX_TURN_CONTENT_CHARS * 2)}],
        idle_seconds=1800,
        max_turns=200,
    )
    assert recorded == 1
    sessions = await memory.list_open_sessions(ORG, "cursor", limit=5)
    turns = await memory.get_turns(ORG, sessions[0]["session_id"])
    assert len(turns[0]["content"]) == MAX_TURN_CONTENT_CHARS
    assert turns[0]["content"].endswith("\u2026")


async def test_ingest_turns_skips_invalid(memory: WorkingMemory) -> None:
    recorded = await ingest_turns(
        memory,
        ORG,
        "cursor",
        [
            {"role": "bogus", "content": "nope"},
            {"role": "user", "content": "   "},
            {"role": "user"},
            "not-a-dict",
            {"role": "assistant", "content": "kept"},
        ],
        idle_seconds=1800,
        max_turns=200,
    )
    assert recorded == 1
