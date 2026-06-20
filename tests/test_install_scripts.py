"""Unified installer routes and script content."""

from __future__ import annotations

import io
import tarfile

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.clients.install_scripts import (
    unified_install_script,
    unified_uninstall_script,
)
from teamshared.server.install_api import (
    handle_install_asset,
    handle_install_index,
    handle_install_sh,
    handle_plugin_bundle,
    handle_uninstall_sh,
)


def test_unified_install_script() -> None:
    body = unified_install_script(base_url="https://teamshared.com")
    assert "#!/usr/bin/env bash" in body
    assert "_ts_choose_harness" in body
    assert "teamshared install:" in body
    assert "TEAMSHARED_INVITE" not in body
    assert "TEAMSHARED_HARNESS" not in body
    assert "_ts_tty" in body
    assert "/dev/tty" in body
    assert "_ts_prompt_token" in body
    assert "/app/keys" in body
    # Accept console API keys (tsk_*).
    assert "tsk_*)" in body
    assert "token should start with tsk_" in body
    assert "https://teamshared.com/mcp" in body
    assert "https://teamshared.com/mcp/" not in body
    # TEAMSHARED_MCP_URL / TEAMSHARED_BASE_URL must be exported so the inline
    # python heredocs (os.environ[...]) can read them — not just shell vars.
    assert "export TEAMSHARED_BASE_URL=" in body
    assert "export TEAMSHARED_MCP_URL=" in body
    assert "_ts_install_hermes_soul" not in body
    assert "/install/assets" in body
    # Hermes ships a conversation-capture shell hook wired by the installer.
    assert "_ts_install_hermes_hook" in body
    assert "teamshared-capture.py" in body
    assert "post_llm_call" in body
    # Project-local install only (current directory).
    assert "INSTALL_ROOT=\"$(pwd)\"" in body
    assert "_ts_choose_cursor_scope" not in body
    assert "global — ~/.cursor" not in body
    assert "${INSTALL_ROOT}/.cursor" in body
    assert "_ts_write_cursor_mcp" in body
    assert "cursor/teamshared.mdc" in body
    cursor_section = body.split("_ts_install_cursor")[1].split("_ts_install_codex")[0]
    assert "teamshared-mcp.snippet.json" not in cursor_section
    assert "install/plugin/teamshared.tar.gz" not in cursor_section
    assert "cp -a \"${root}\" \"${plugin_dir}\"" not in cursor_section
    assert "${INSTALL_ROOT}/.codex/config.toml" in body
    assert "${INSTALL_ROOT}/.hermes/agent-hooks" in body
    assert "${INSTALL_ROOT}/.claude" in body
    assert "claude_desktop_config.json" in body
    assert "${INSTALL_ROOT}/.openclaw" in body
    assert "teamshared-mcp.yaml" in body
    assert "${HOME}/.config/teamshared" not in body
    # Restart guidance is per-harness, not hardcoded to Cursor.
    assert "Restart Hermes" in body
    assert "Quit and reopen Claude Desktop" in body
    assert "Done. Restart your agent (Cursor: Developer → Reload Window)." not in body


def test_unified_uninstall_script() -> None:
    body = unified_uninstall_script(base_url="https://teamshared.com")
    assert "#!/usr/bin/env bash" in body
    assert "teamshared uninstall:" in body
    assert "_ts_choose_harness" in body
    # Offers an "all" option that covers every harness.
    assert "6) all" in body
    assert "Enter choice [1-6]" in body
    # Never prompts for or touches a bearer token (pure removal).
    assert "TEAMSHARED_TOKEN" not in body
    assert "_ts_prompt_token" not in body
    # Removes project-local files under INSTALL_ROOT only.
    assert 'INSTALL_ROOT="$(pwd)"' in body
    assert "${INSTALL_ROOT}/.cursor/plugins/local/teamshared" in body
    assert "${INSTALL_ROOT}/.cursor/rules/teamshared.mdc" in body
    assert "${INSTALL_ROOT}/.codex/teamshared-mcp.toml" in body
    assert "${INSTALL_ROOT}/.hermes/agent-hooks/teamshared-capture.py" in body
    assert "${INSTALL_ROOT}/.claude/claude_desktop_config.json" in body
    assert "${INSTALL_ROOT}/.openclaw/teamshared-mcp.yaml" in body
    assert "${HOME}/.codex" not in body
    # Surgically edits shared config rather than deleting it wholesale.
    assert "_ts_remove_json_mcp" in body
    assert "_ts_remove_codex_block" in body
    assert "_ts_remove_hermes_block" in body


def test_install_routes() -> None:
    app = Starlette(
        routes=[
            Route("/install", handle_install_index, methods=["GET"]),
            Route("/install.sh", handle_install_sh, methods=["GET"]),
            Route("/uninstall.sh", handle_uninstall_sh, methods=["GET"]),
            Route("/install/assets/{asset_path:path}", handle_install_asset, methods=["GET"]),
            Route("/install/plugin/teamshared.tar.gz", handle_plugin_bundle, methods=["GET"]),
        ]
    )
    with TestClient(app, base_url="https://teamshared.com") as client:
        index = client.get("/install")
        assert index.status_code == 200
        assert "install.sh" in index.text
        assert "uninstall.sh" in index.text
        assert "./.cursor" in index.text

        uninstall = client.get("/uninstall.sh")
        assert uninstall.status_code == 200
        assert uninstall.headers["content-type"].startswith("text/x-shellscript")
        assert "Enter choice [1-6]" in uninstall.text

        script = client.get("/install.sh")
        assert script.status_code == 200
        assert script.headers["content-type"].startswith("text/x-shellscript")
        assert "Enter choice [1-5]" in script.text

        codex = client.get("/install/assets/codex/mcp.toml")
        assert codex.status_code == 200
        assert "https://teamshared.com/mcp" in codex.text
        assert "__MCP_URL__" not in codex.text

        cursor_mcp = client.get("/install/assets/cursor/mcp.json")
        assert cursor_mcp.status_code == 200
        assert "__TEAMSHARED_TOKEN__" in cursor_mcp.text

        cursor_rule = client.get("/install/assets/cursor/teamshared.mdc")
        assert cursor_rule.status_code == 200
        assert "teamshared Memory Protocol" in cursor_rule.text
        assert "version:" in cursor_rule.text

        hermes_hook = client.get("/install/assets/hermes/capture.py")
        assert hermes_hook.status_code == 200
        assert "post_llm_call" in hermes_hook.text
        assert "/sessions/turns" in hermes_hook.text
        assert "_HOOK_DIR" in hermes_hook.text

        hermes_hooks_yaml = client.get("/install/assets/hermes/hooks.yaml")
        assert hermes_hooks_yaml.status_code == 200
        assert "post_llm_call" in hermes_hooks_yaml.text

        hermes_protocol = client.get("/install/assets/hermes/protocol.md")
        assert hermes_protocol.status_code == 200
        assert "sessions_list" in hermes_protocol.text
        assert "memory_remember" in hermes_protocol.text
        assert "save to teamshared" in hermes_protocol.text.lower()

        bundle = client.get("/install/plugin/teamshared.tar.gz")
        assert bundle.status_code == 200
        with tarfile.open(fileobj=io.BytesIO(bundle.content), mode="r:gz") as tar:
            names = tar.getnames()
        assert any(n.endswith("rules/teamshared.mdc") for n in names)
