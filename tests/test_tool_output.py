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
async def test_normalize_compressed_dict_replaces_body_not_duplicates() -> None:
    """Compression must shrink the payload — never original body + preview."""
    settings = Settings(
        mcp_tool_output_max_record_chars=4000,
        compress_min_chars=200,
        compress_target_ratio=0.3,
    )
    store = MagicMock()
    store.put = AsyncMock(return_value="ccr_test_ref")
    payload = {"answer": "word " * 2000, "query": "q"}
    original_len = len(json.dumps(payload, separators=(",", ":")))
    result = await normalize_tool_output(
        settings,
        "memory_think",
        json.dumps(payload),
        org_scope="org:test",
        store=store,
    )
    assert result.compressed is True
    out_text = (
        json.dumps(result.body) if isinstance(result.body, dict) else str(result.body)
    )
    # The compressed text replaces the body — before the fix the original dict
    # rode along with the preview and the output was *larger* than the input.
    assert len(out_text) < original_len * 0.6
    assert result.chars_saved > 0
    assert "teamshared compressed" in out_text
    assert "ccr_test_ref" in out_text


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
