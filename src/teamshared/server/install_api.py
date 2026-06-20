"""HTTP handlers for the unified installer and plugin-served static assets."""

from __future__ import annotations

import io
import tarfile

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from teamshared.clients.install_assets import plugin_root, resolve_install_asset
from teamshared.clients.install_scripts import (
    install_index_html,
    unified_install_script,
    unified_uninstall_script,
)

_ASSET_PLACEHOLDER = "__MCP_URL__"


def _mcp_url(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/mcp"


def _plugin_tarball_bytes() -> bytes | None:
    root = plugin_root()
    if root is None:
        return None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(root, arcname="teamshared")
    return buf.getvalue()


async def handle_install_index(request: Request) -> HTMLResponse:
    base = str(request.base_url).rstrip("/")
    return HTMLResponse(install_index_html(base_url=base))


async def handle_install_sh(request: Request) -> PlainTextResponse:
    base = str(request.base_url).rstrip("/")
    body = unified_install_script(base_url=base)
    return PlainTextResponse(
        body,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="install.sh"'},
    )


async def handle_uninstall_sh(request: Request) -> PlainTextResponse:
    base = str(request.base_url).rstrip("/")
    body = unified_uninstall_script(base_url=base)
    return PlainTextResponse(
        body,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="uninstall.sh"'},
    )


async def handle_install_asset(request: Request) -> Response:
    rel = request.path_params.get("asset_path", "").lstrip("/")
    path = resolve_install_asset(rel)
    if path is None:
        return PlainTextResponse("not found", status_code=404)

    suffix = path.suffix.lower()
    if suffix in {".json", ".yaml", ".yml", ".toml", ".sh", ".md", ".mdc", ".py"}:
        text = path.read_text(encoding="utf-8")
        if _ASSET_PLACEHOLDER in text:
            text = text.replace(_ASSET_PLACEHOLDER, _mcp_url(request))
        media = "application/json" if suffix == ".json" else "text/plain; charset=utf-8"
        if suffix == ".sh":
            media = "text/x-shellscript; charset=utf-8"
        if suffix == ".py":
            media = "text/x-python; charset=utf-8"
        return PlainTextResponse(text, media_type=media)

    return FileResponse(path)


async def handle_plugin_bundle(_: Request) -> Response:
    data = _plugin_tarball_bytes()
    if data is None:
        return PlainTextResponse("plugin bundle unavailable", status_code=503)
    return Response(
        content=data,
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="teamshared.tar.gz"'},
    )
