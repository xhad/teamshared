"""Unit tests for MCP audit payload helpers."""

from __future__ import annotations

from scripts.mcp_tool_audit import (
    _parse_json_from_compressed_output,
    payload_has_key,
    unwrap_tool_payload,
)


def test_unwrap_result_envelope() -> None:
    assert unwrap_tool_payload({"result": {"name": "x"}}) == {"name": "x"}


def test_unwrap_compressed_output_blob() -> None:
    raw = (
        "[teamshared compressed text 100 → ~50 chars]\n"
        '{"records":[{"id":"m1"}],"query":"q"}\n'
        "ref=ccr_abc123\n"
    )
    assert unwrap_tool_payload({"output": raw}) == {
        "records": [{"id": "m1"}],
        "query": "q",
    }


def test_payload_has_key_on_compressed_blob() -> None:
    raw = {"output": 'header\n{"records":[{"id":"m1"}]}\n'}
    assert payload_has_key(raw, "records") is True


def test_parse_json_from_compressed_output() -> None:
    text = "header\n{\"episodes\":[]}\nref=ccr_x"
    assert _parse_json_from_compressed_output(text) == {"episodes": []}
