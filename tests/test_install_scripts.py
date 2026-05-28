"""Unified installer routes and script content."""

from __future__ import annotations

import io
import tarfile

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.clients.install_scripts import unified_install_script
from teamshared.server.install_api import (
    handle_install_asset,
    handle_install_index,
    handle_install_sh,
    handle_plugin_bundle,
)


def test_unified_install_script() -> None:
    body = unified_install_script(base_url="https://actx.teamshared.com")
    assert "#!/usr/bin/env bash" in body
    assert "_ts_choose_harness" in body
    assert "teamshared install:" in body
    assert "TEAMSHARED_INVITE" not in body
    assert "TEAMSHARED_HARNESS" not in body
    assert "_ts_tty" in body
    assert "/dev/tty" in body
    assert "_ts_prompt_token" in body
    assert "/get-token" in body
    assert "https://actx.teamshared.com/mcp" in body
    assert "/install/assets" in body
    # Restart guidance is per-harness, not hardcoded to Cursor.
    assert "Restart Hermes" in body
    assert "Quit and reopen Claude Desktop" in body
    assert "Done. Restart your agent (Cursor: Developer → Reload Window)." not in body


def test_install_routes() -> None:
    app = Starlette(
        routes=[
            Route("/install", handle_install_index, methods=["GET"]),
            Route("/install.sh", handle_install_sh, methods=["GET"]),
            Route("/install/assets/{asset_path:path}", handle_install_asset, methods=["GET"]),
            Route("/install/plugin/teamshared.tar.gz", handle_plugin_bundle, methods=["GET"]),
        ]
    )
    with TestClient(app, base_url="https://actx.teamshared.com") as client:
        index = client.get("/install")
        assert index.status_code == 200
        assert "install.sh" in index.text

        script = client.get("/install.sh")
        assert script.status_code == 200
        assert script.headers["content-type"].startswith("text/x-shellscript")
        assert "Enter choice [1-5]" in script.text

        codex = client.get("/install/assets/codex/mcp.toml")
        assert codex.status_code == 200
        assert "https://actx.teamshared.com/mcp" in codex.text
        assert "__MCP_URL__" not in codex.text

        cursor_mcp = client.get("/install/assets/cursor/mcp.json")
        assert cursor_mcp.status_code == 200
        assert "__TEAMSHARED_TOKEN__" in cursor_mcp.text

        bundle = client.get("/install/plugin/teamshared.tar.gz")
        assert bundle.status_code == 200
        with tarfile.open(fileobj=io.BytesIO(bundle.content), mode="r:gz") as tar:
            names = tar.getnames()
        assert any(n.endswith("rules/teamshared.mdc") for n in names)
