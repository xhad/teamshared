"""HTTP handlers for the unified installer, static assets, and plugin bundle."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from teamshared.clients.install_scripts import (
    INSTALL_ASSETS_PATH,
    PLUGIN_BUNDLE_PATH,
    install_index_html,
    unified_install_script,
    unified_uninstall_script,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_PLUGIN = _REPO_ROOT / "plugins" / "teamshared"
_REPO_ASSETS = _REPO_ROOT / "install_assets"

_ASSET_PLACEHOLDER = "__MCP_URL__"


def _plugin_source_dir() -> Path | None:
    docker = Path(PLUGIN_BUNDLE_PATH)
    if docker.is_dir():
        return docker
    if _REPO_PLUGIN.is_dir():
        return _REPO_PLUGIN
    return None


def _assets_root() -> Path | None:
    docker = Path(INSTALL_ASSETS_PATH)
    if docker.is_dir():
        return docker
    if _REPO_ASSETS.is_dir():
        return _REPO_ASSETS
    return None


def _mcp_url(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/mcp"


def _plugin_tarball_bytes() -> bytes | None:
    root = _plugin_source_dir()
    if root is None:
        return None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(root, arcname="teamshared")
    return buf.getvalue()


def _resolve_asset(rel: str) -> Path | None:
    root = _assets_root()
    if root is None:
        return None
    path = (root / rel).resolve()
    if not str(path).startswith(str(root.resolve())):
        return None
    return path if path.is_file() else None


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
    if not rel or ".." in rel.split("/"):
        return PlainTextResponse("not found", status_code=404)

    path = _resolve_asset(rel)
    if path is None:
        return PlainTextResponse("not found", status_code=404)

    suffix = path.suffix.lower()
    if suffix in {".json", ".yaml", ".yml", ".toml", ".sh", ".md"}:
        text = path.read_text(encoding="utf-8")
        if _ASSET_PLACEHOLDER in text:
            text = text.replace(_ASSET_PLACEHOLDER, _mcp_url(request))
        media = "application/json" if suffix == ".json" else "text/plain; charset=utf-8"
        if suffix == ".sh":
            media = "text/x-shellscript; charset=utf-8"
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
