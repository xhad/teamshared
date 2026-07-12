"""Tests for MCP tool output normalization middleware."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as mt
import pytest
from fastmcp.tools import ToolResult

from teamshared.server.mcp_output_middleware import (
    ToolOutputNormalizeMiddleware,
    _ensure_structured,
    _rebuild_result,
)


def test_rebuild_result_wraps_string_for_object_schema() -> None:
    original = ToolResult(
        structured_content={"records": []},
        meta=None,
    )
    rebuilt = _rebuild_result(original, "compressed preview")
    assert rebuilt.structured_content == {"output": "compressed preview"}


def test_rebuild_result_preserves_wrap_result_shape() -> None:
    original = ToolResult(
        structured_content={"result": {"name": "x"}},
        meta={"fastmcp": {"wrap_result": True}},
    )
    rebuilt = _rebuild_result(original, {"name": "y"})
    assert rebuilt.structured_content == {"result": {"name": "y"}}


def test_ensure_structured_backfills_from_text_content() -> None:
    payload = {"records": [{"id": "m1", "content": "hello"}]}
    original = ToolResult(
        content=[mt.TextContent(type="text", text=json.dumps(payload))],
    )
    fixed = _ensure_structured(original, payload)
    assert fixed.structured_content == payload


@pytest.mark.asyncio
async def test_middleware_backfills_structured_content_when_unchanged() -> None:
    middleware = ToolOutputNormalizeMiddleware()
    payload = {"records": [], "query": "teamshared"}
    inner = ToolResult(content=[mt.TextContent(type="text", text=json.dumps(payload))])

    async def call_next(_ctx: object) -> ToolResult:
        return inner

    ctx = MagicMock()
    ctx.message = MagicMock(name="memory_recall")

    with (
        patch("teamshared.server.mcp_output_middleware.get_settings") as gs,
        patch("teamshared.server.mcp_output_middleware.get_state") as gst,
        patch("teamshared.server.mcp_output_middleware.current_principal", return_value=None),
        patch(
            "teamshared.server.mcp_output_middleware.normalize_tool_output",
            new=AsyncMock(
                return_value=MagicMock(
                    body=payload,
                    compressed=False,
                    cleaned=False,
                    chars_saved=0,
                )
            ),
        ),
    ):
        settings = MagicMock()
        settings.mcp_tool_output_normalize_enabled = True
        gs.return_value = settings
        gst.return_value = MagicMock(working=MagicMock())
        out = await middleware.on_call_tool(ctx, call_next)

    assert out.structured_content == payload
