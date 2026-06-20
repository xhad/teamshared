"""Unit tests for context compression."""

from __future__ import annotations

import json

import pytest

from teamshared.compress.engine import compress_messages, compress_text
from teamshared.compress.smart_crusher import compress_json_array, try_compress_json_text
from teamshared.config import Settings


def test_compress_json_array_samples_large_payload() -> None:
    items = [{"id": i, "status": "ok" if i % 10 else "error"} for i in range(200)]
    kept, meta = compress_json_array(items, max_items=20)
    assert meta["original_count"] == 200
    assert len(kept) <= 20
    assert any(item.get("status") == "error" for item in kept)


def test_try_compress_json_text_rewrites_array() -> None:
    payload = json.dumps([{"line": i, "msg": f"row {i}"} for i in range(100)])
    out, changed, meta = try_compress_json_text(payload, max_items=15)
    assert changed is True
    assert meta is not None
    assert "teamshared compressed" in out
    assert "100" in out


def test_compress_text_skips_short_content() -> None:
    settings = Settings(compress_min_chars=800)
    out, changed, _ = compress_text("short", settings)
    assert changed is False
    assert out == "short"


def test_compress_messages_preserves_user_role() -> None:
    settings = Settings(compress_min_chars=10, compress_json_max_items=5)
    big = json.dumps([{"n": i} for i in range(50)])
    messages = [
        {"role": "user", "content": "find errors"},
        {"role": "tool", "content": big},
    ]
    result = compress_messages(settings, messages)
    assert result.compressed is True
    assert result.messages[0]["content"] == "find errors"
    assert "teamshared compressed" in result.messages[1]["content"]


def test_compress_messages_short_tool_output_passes_through() -> None:
    settings = Settings(compress_min_chars=5000)
    messages = [{"role": "tool", "content": "x" * 100}]
    result = compress_messages(settings, messages)
    assert result.compressed is False
    assert result.messages == messages


def test_compress_skips_teamshared_context_pack() -> None:
    settings = Settings(compress_min_chars=100, compress_target_ratio=0.35)
    pack = "## TeamShared context\n\n" + ("- smoke fact\n" * 80)
    messages = [
        {"role": "system", "content": pack},
        {"role": "user", "content": "test"},
    ]
    result = compress_messages(settings, messages)
    assert result.compressed is False
    assert result.messages[0]["content"] == pack
