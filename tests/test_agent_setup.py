"""Agent setup snippet generation."""

from __future__ import annotations

from teamshared.clients.agent_setup import (
    agent_setup,
    load_teamshared_memory_rule_mdc,
    normalize_agent_type,
)


def test_normalize_agent_type() -> None:
    assert normalize_agent_type("cursor") == "cursor"
    assert normalize_agent_type("Cursor") == "cursor"
    assert normalize_agent_type("cursor-chad") == "cursor"
    assert normalize_agent_type("hermes-bot") == "hermes"
    assert normalize_agent_type("codex") == "codex"
    assert normalize_agent_type("codex-work") == "codex"
    assert normalize_agent_type("unknown") is None


def test_cursor_setup_includes_mcp_json() -> None:
    setup = agent_setup(
        "cursor",
        mcp_url="https://actx.teamshared.com/mcp",
        token="teamshared_testtoken",
    )
    assert setup is not None
    assert setup.snippet.startswith("{")
    assert "mcpServers" in setup.snippet
    assert "teamshared_testtoken" in setup.snippet
    assert "plugins/local" not in setup.snippet
    assert "symlink" not in setup.snippet.lower()
    assert setup.config_path == "~/.cursor/rules/teamshared.mdc and ~/.cursor/mcp.json"
    assert any("Memory rule section" in step for step in setup.steps)
    assert any("Settings → MCP" in step for step in setup.steps)
    assert setup.rule_mdc is not None
    assert "teamshared Memory Protocol" in setup.rule_mdc
    assert "alwaysApply: true" in setup.rule_mdc
    assert any("Memory rule block below" in step for step in setup.rule_install_steps)


def test_load_teamshared_memory_rule_mdc() -> None:
    mdc = load_teamshared_memory_rule_mdc()
    assert mdc.startswith("---")
    assert "memory_recall" in mdc


def test_codex_setup_uses_inline_token_toml() -> None:
    setup = agent_setup(
        "codex",
        mcp_url="https://actx.teamshared.com/mcp",
        token="teamshared_testtoken",
    )
    assert setup is not None
    assert "[mcp_servers.teamshared]" in setup.snippet
    assert "http_headers" in setup.snippet
    assert "Bearer teamshared_testtoken" in setup.snippet
    # No env-var indirection for codex anymore.
    assert "bearer_token_env_var" not in setup.snippet
    assert "export TEAMSHARED_TOKEN" not in setup.snippet
