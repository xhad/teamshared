"""Agent setup snippet generation."""

from __future__ import annotations

from teamshared.clients.agent_setup import (
    RULE_VERSION_FALLBACK,
    agent_setup,
    canonical_install_script_url,
    load_teamshared_memory_rule_mdc,
    normalize_agent_type,
    parse_rule_version,
    teamshared_rule_version,
)


def test_parse_rule_version_from_frontmatter() -> None:
    md = "---\ndescription: x\nalwaysApply: true\nversion: 2.3.4\n---\n# Body\n"
    assert parse_rule_version(md) == "2.3.4"


def test_parse_rule_version_missing_returns_fallback() -> None:
    assert parse_rule_version("# no version here\n") == RULE_VERSION_FALLBACK


def test_canonical_rule_is_versioned() -> None:
    # The shipped rule must carry a real (non-fallback) version marker.
    version = teamshared_rule_version()
    assert version != RULE_VERSION_FALLBACK
    assert version in load_teamshared_memory_rule_mdc()


def test_canonical_install_script_url() -> None:
    assert canonical_install_script_url() == "https://teamshared.com/install.sh"


def test_normalize_agent_type() -> None:
    assert normalize_agent_type("cursor") == "cursor"
    assert normalize_agent_type("Cursor") == "cursor"
    assert normalize_agent_type("cursor-chad") == "cursor"
    assert normalize_agent_type("hermes-bot") == "hermes"
    assert normalize_agent_type("codex") == "codex"
    assert normalize_agent_type("codex-work") == "codex"
    assert normalize_agent_type("pi") == "pi"
    assert normalize_agent_type("unknown") is None


def test_cursor_setup_includes_mcp_json() -> None:
    setup = agent_setup(
        "cursor",
        mcp_url="https://teamshared.com/mcp",
        token="tsk_testtoken_secret",
    )
    assert setup is not None
    assert setup.snippet.startswith("{")
    assert "mcpServers" in setup.snippet
    assert "tsk_testtoken_secret" in setup.snippet
    assert "plugins/local" not in setup.snippet
    assert "symlink" not in setup.snippet.lower()
    assert setup.config_path == "~/.cursor/rules/teamshared.mdc and ~/.cursor/mcp.json"
    assert any("install.sh" in step for step in setup.steps)
    # Cursor installs globally under ~/.cursor (outside any repo), so there is
    # no .gitignore step.
    assert not any(".gitignore" in step for step in setup.steps)
    assert setup.rule_mdc is not None
    assert "teamshared Memory Protocol" in setup.rule_mdc
    assert "alwaysApply: true" in setup.rule_mdc
    assert any("~/.cursor/rules" in step for step in setup.rule_install_steps)


def test_load_teamshared_memory_rule_mdc() -> None:
    mdc = load_teamshared_memory_rule_mdc()
    assert mdc.startswith("---")
    assert "memory_recall" in mdc
    assert "github=" in mdc
    # repo= is resolved as a git-root path slug (strip leading "/", replace "/" with "-").
    assert "strip leading" in mdc
    assert "replace `/` with `-`" in mdc


def test_codex_setup_uses_inline_token_toml() -> None:
    setup = agent_setup(
        "codex",
        mcp_url="https://teamshared.com/mcp",
        token="tsk_testtoken_secret",
    )
    assert setup is not None
    assert "[mcp_servers.teamshared]" in setup.snippet
    assert "http_headers" in setup.snippet
    assert "Bearer tsk_testtoken_secret" in setup.snippet
    # No env-var indirection for codex anymore.
    assert "bearer_token_env_var" not in setup.snippet
    assert "export TEAMSHARED_TOKEN" not in setup.snippet


def test_hermes_setup_uses_mcp_url_without_trailing_slash() -> None:
    setup = agent_setup(
        "hermes",
        mcp_url="https://teamshared.com/mcp",
        token="tsk_testtoken_secret",
    )
    assert setup is not None
    # The server rewrites /mcp -> /mcp/ in-place, so we emit the bare /mcp URL.
    assert "url: https://teamshared.com/mcp\n" in setup.snippet
    assert "https://teamshared.com/mcp/" not in setup.snippet
    assert "teamshared-protocol" in setup.snippet or "protocol" in setup.snippet.lower()


def test_pi_setup_uses_project_mcp_json() -> None:
    setup = agent_setup(
        "pi",
        mcp_url="https://teamshared.com/mcp",
        token="tsk_testtoken_secret",
    )
    assert setup is not None
    assert setup.config_path == "./.mcp.json"
    assert "mcpServers" in setup.snippet
    assert "tsk_testtoken_secret" in setup.snippet
    assert any("pi-mcp-adapter" in step for step in setup.steps)
    assert any("/mcp" in step for step in setup.steps)
