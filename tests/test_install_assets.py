"""Install asset resolution from the plugin bundle."""

from __future__ import annotations

from teamshared.clients.install_assets import (
    install_dir,
    plugin_root,
    resolve_install_asset,
)


def test_plugin_root_exists_in_repo() -> None:
    root = plugin_root()
    assert root is not None
    assert (root / "rules" / "teamshared.mdc").is_file()


def test_install_dir_exists_in_repo() -> None:
    install = install_dir()
    assert install is not None
    assert (install / "codex" / "mcp.toml").is_file()


def test_resolve_install_template() -> None:
    path = resolve_install_asset("codex/mcp.toml")
    assert path is not None
    assert path.name == "mcp.toml"
    assert "__MCP_URL__" in path.read_text(encoding="utf-8")


def test_resolve_rule_alias() -> None:
    path = resolve_install_asset("cursor/teamshared.mdc")
    assert path is not None
    assert path.parent.name == "rules"
    assert "teamshared Memory Protocol" in path.read_text(encoding="utf-8")


def test_resolve_protocol_alias() -> None:
    path = resolve_install_asset("hermes/protocol.md")
    assert path is not None
    assert path.name == "protocol.md"
    assert path.parent.name == "clients"


def test_resolve_rejects_traversal() -> None:
    assert resolve_install_asset("../rules/teamshared.mdc") is None
    assert resolve_install_asset("codex/../../rules/teamshared.mdc") is None
