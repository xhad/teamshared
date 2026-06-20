"""Tests for MCP tool output normalization."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.compress.tool_output import clean_tool_payload, normalize_tool_output
from teamshared.config import Settings


@pytest.mark.asyncio
async def test_clean_recall_trims_long_record_content() -> None:
    settings = Settings(mcp_tool_output_max_record_chars=100)
    payload = {
        "records": [
            {"id": "m1", "content": "x" * 500, "embedding": [0.1, 0.2]},
        ],
    }
    cleaned, changed = clean_tool_payload("memory_recall", payload, settings=settings)
    assert changed is True
    assert "embedding" not in cleaned["records"][0]
    assert len(cleaned["records"][0]["content"]) <= 100


@pytest.mark.asyncio
async def test_normalize_compresses_large_json_tool_output() -> None:
    settings = Settings(compress_min_chars=200, compress_json_max_items=5)
    store = MagicMock()
    store.put = AsyncMock(return_value="ccr_test_ref")
    big = json.dumps([{"n": i, "msg": f"row {i}"} for i in range(100)])
    result = await normalize_tool_output(
        settings,
        "MCP:Shell",
        big,
        org_scope="org:test",
        store=store,
    )
    assert result.compressed is True
    assert result.ref == "ccr_test_ref"
    text = json.dumps(result.body) if isinstance(result.body, dict) else str(result.body)
    assert "teamshared compressed" in text or result.chars_saved > 0


@pytest.mark.asyncio
async def test_normalize_clean_only_reports_chars_saved() -> None:
    settings = Settings(mcp_tool_output_max_record_chars=100, compress_min_chars=800)
    store = MagicMock()
    big = json.dumps({"records": [{"id": "m1", "content": "x" * 2000, "embedding": [0.1]}]})
    result = await normalize_tool_output(
        settings,
        "memory_recall",
        big,
        org_scope="org:test",
        store=store,
    )
    assert result.cleaned is True
    assert result.compressed is False
    assert result.chars_saved > 1000
    assert "_teamshared" not in result.body
    store.put.assert_not_called()


@pytest.mark.asyncio
async def test_normalize_skips_health() -> None:
    settings = Settings()
    store = MagicMock()
    result = await normalize_tool_output(
        settings,
        "health",
        '{"status":"ok"}',
        org_scope="org:test",
        store=store,
    )
    assert result.compressed is False
    store.put.assert_not_called()
