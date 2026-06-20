"""Harness-agnostic conversation capture at the MCP tool-call boundary.

Client-side hooks (e.g. the Cursor plugin's ``stop`` hook) only fire in one
harness. The one layer every harness shares is the MCP server: they all call
tools at ``/mcp`` with a bearer token. This FastMCP middleware records each
authenticated tool call as a single turn against a per-agent implicit working
session, so the shared brain captures activity regardless of harness and
without any explicit ``memory_session_*`` ritual.

All capture work is best-effort: failures are swallowed so a capture problem
can never break the underlying tool call. The session lifecycle (rollover +
distillation) lives in :meth:`WorkingMemory.record_tool_call`; this middleware
only resolves identity, formats a compact turn, and delegates.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from teamshared.auth import current_agent, current_principal
from teamshared.config import get_settings
from teamshared.logging import get_logger
from teamshared.memory.working import WorkingMemory
from teamshared.metrics import METRICS
from teamshared.server.state import get_state

log = get_logger(__name__)

# Tools whose calls are pure liveness/noise and not worth recording.
_SKIP_TOOLS = frozenset({"health"})

_INGEST_ROLES = frozenset({"user", "assistant", "tool", "system"})

# Boundary caps for POST /sessions/turns: any bearer holder can call it, so
# bound both the batch size and each turn's stored length.
MAX_TURNS_PER_REQUEST = 200
MAX_TURN_CONTENT_CHARS = 8000


async def ingest_turns(
    working: WorkingMemory,
    org_id: Any,
    agent: str,
    turns: list[Any],
    *,
    idle_seconds: int,
    max_turns: int,
    capability: str = "raw_turns",
    source: str = "sessions_turns",
) -> int:
    """Append validated conversation turns to ``agent``'s capture session.

    Shared by the ``POST /sessions/turns`` route and its tests. Turns with an
    unknown role or empty content are skipped. Returns the number recorded.
    """
    recorded = 0
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if role not in _INGEST_ROLES:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        if len(content) > MAX_TURN_CONTENT_CHARS:
            content = content[: MAX_TURN_CONTENT_CHARS - 1] + "\u2026"
        await working.record_turn(
            org_id, agent, role, content, idle_seconds=idle_seconds, max_turns=max_turns
        )
        METRICS.capture_recorded.inc(capability=capability, source=source)
        recorded += 1
    return recorded

_MAX_VALUE_CHARS = 120
_MAX_CONTENT_CHARS = 500


def _short(value: Any, limit: int = _MAX_VALUE_CHARS) -> str:
    """Render one argument value as a compact single-line string."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            text = str(value)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "\u2026"
    return text


def _summarize_arguments(arguments: dict[str, Any] | None) -> str:
    if not arguments:
        return ""
    parts: list[str] = []
    for key, value in arguments.items():
        # ``agent`` is an attribution override, not signal about the activity.
        if key == "agent":
            continue
        parts.append(f"{key}={_short(value)}")
    return ", ".join(parts)


def _build_turn(name: str, arguments: dict[str, Any] | None, *, ok: bool) -> str:
    summary = _summarize_arguments(arguments)
    status = "ok" if ok else "error"
    content = f"{name}({summary}) -> {status}"
    if len(content) > _MAX_CONTENT_CHARS:
        return content[: _MAX_CONTENT_CHARS - 1] + "\u2026"
    return content


class ToolCallCaptureMiddleware(Middleware):
    """Record every authenticated tool call into a per-agent working session."""

    def __init__(self, *, idle_seconds: int, max_turns: int) -> None:
        self._idle_seconds = idle_seconds
        self._max_turns = max_turns

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            result = await call_next(context)
        except Exception:
            await self._capture(context, ok=False)
            raise
        await self._capture(context, ok=True)
        return result

    async def _capture(
        self, context: MiddlewareContext[mt.CallToolRequestParams], *, ok: bool
    ) -> None:
        try:
            identity = current_agent()
            if identity is None:
                return
            message = context.message
            name = getattr(message, "name", None)
            if not name or name in _SKIP_TOOLS:
                return
            principal = current_principal()
            org_id = principal.org_id if principal else get_settings().default_org_id
            state = get_state()
            content = _build_turn(name, getattr(message, "arguments", None), ok=ok)
            await state.working.record_tool_call(
                org_id,
                identity.agent,
                content,
                idle_seconds=self._idle_seconds,
                max_turns=self._max_turns,
            )
            METRICS.capture_recorded.inc(capability="tool_calls", source="mcp")
        except Exception as exc:  # never let capture break a tool call
            log.warning("tool_call_capture_failed", error=str(exc))
