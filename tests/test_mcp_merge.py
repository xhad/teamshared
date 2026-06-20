"""Tests for JSON MCP config merge helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teamshared.clients.mcp_merge import merge_teamshared_mcp_config


def test_merge_creates_config_when_missing(tmp_path: Path) -> None:
    dest = tmp_path / ".cursor" / "mcp.json"
    merge_teamshared_mcp_config(
        dest, mcp_url="https://teamshared.com/mcp", token="tsk_test"
    )
    data = json.loads(dest.read_text())
    assert data["mcpServers"]["teamshared"]["url"] == "https://teamshared.com/mcp"
    assert data["mcpServers"]["teamshared"]["headers"]["Authorization"] == "Bearer tsk_test"


def test_merge_preserves_other_servers(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"url": "https://example.com/mcp", "headers": {}},
                },
                "someOtherKey": 1,
            }
        )
        + "\n"
    )
    merge_teamshared_mcp_config(
        dest, mcp_url="https://teamshared.com/mcp", token="tsk_new"
    )
    data = json.loads(dest.read_text())
    assert data["someOtherKey"] == 1
    assert data["mcpServers"]["other"]["url"] == "https://example.com/mcp"
    assert data["mcpServers"]["teamshared"]["headers"]["Authorization"] == "Bearer tsk_new"


def test_merge_updates_existing_teamshared_entry(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "teamshared": {
                        "url": "https://old.example/mcp",
                        "transport": "stdio",
                        "headers": {"Authorization": "Bearer tsk_old", "X-Extra": "keep"},
                    }
                }
            }
        )
        + "\n"
    )
    merge_teamshared_mcp_config(
        dest, mcp_url="https://teamshared.com/mcp", token="tsk_new"
    )
    entry = json.loads(dest.read_text())["mcpServers"]["teamshared"]
    assert entry["url"] == "https://teamshared.com/mcp"
    assert entry["transport"] == "stdio"
    assert entry["headers"]["Authorization"] == "Bearer tsk_new"
    assert entry["headers"]["X-Extra"] == "keep"


def test_merge_rejects_invalid_json(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text("{ not json")
    with pytest.raises(ValueError, match="invalid JSON"):
        merge_teamshared_mcp_config(
            dest, mcp_url="https://teamshared.com/mcp", token="tsk_test"
        )
