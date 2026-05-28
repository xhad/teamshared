"""Agent setup snippet generation."""

from __future__ import annotations

from teamshared.clients.agent_setup import agent_setup, normalize_agent_type


def test_normalize_agent_type() -> None:
    assert normalize_agent_type("cursor") == "cursor"
    assert normalize_agent_type("Cursor") == "cursor"
    assert normalize_agent_type("cursor-chad") == "cursor"
    assert normalize_agent_type("hermes-bot") == "hermes"
    assert normalize_agent_type("unknown") is None


def test_cursor_setup_includes_mcp_json() -> None:
    setup = agent_setup(
        "cursor",
        mcp_url="https://actx.teamshared.com/mcp",
        token="teamshared_testtoken",
    )
    assert setup is not None
    assert "mcpServers" in setup.snippet
    assert "teamshared_testtoken" in setup.snippet
    assert setup.config_path == "~/.cursor/mcp.json"
