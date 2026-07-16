"""Public shared-file view handler for ``GET /s/{share_token}``.

No-auth (whitelisted as ``PUBLIC_UNAUTH`` in :mod:`teamshared.server.route_policy`).
Reads a published shared file + its versions through the SECURITY DEFINER
functions in :mod:`teamshared.memory.shared_files` (over an RLS-less
``admin()`` connection) and renders a standalone Jinja2 template with a
collapsible version-history sidebar.

Content is rendered through the allowlist sanitizer
(:func:`teamshared.server.markdown_safe.render_markdown_safe` for markdown,
:func:`sanitize_html` for raw HTML) so agent-authored files can never inject
executable HTML on the public page.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.templating import Jinja2Templates
from pathlib import Path

from teamshared.logging import get_logger
from teamshared.server.markdown_safe import render_markdown_safe, sanitize_html

log = get_logger(__name__)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _render_content(content: str, content_format: str) -> str:
    if content_format == "html":
        return sanitize_html(content)
    return render_markdown_safe(content)


async def handle_shared_file_view(request: Request, state: Any) -> Response:
    """Render a published shared file at ``/s/{share_token}``.

    Optional ``?v={version}`` renders a specific historical version.
    """
    share_token = str(request.path_params["share_token"])
    requested_version: int | None = None
    raw_v = request.query_params.get("v")
    if raw_v:
        try:
            requested_version = int(raw_v)
        except ValueError:
            requested_version = None

    try:
        if requested_version is not None:
            file = await state.services.shared_files.get_published_version(
                share_token, requested_version
            )
        else:
            file = await state.services.shared_files.get_published_by_token(share_token)
    except Exception as exc:
        log.warning("shared_file_view_failed", share_token=share_token, error=str(exc))
        return HTMLResponse(
            "<h1>Shared file unavailable</h1><p>This file could not be loaded.</p>",
            status_code=503,
        )

    if file is None:
        return HTMLResponse(
            "<h1>Shared file not found</h1>"
            "<p>This file is private, unpublished, or has been deleted.</p>",
            status_code=404,
        )

    try:
        versions = await state.services.shared_files.list_published_versions(share_token)
    except Exception as exc:
        log.warning("shared_file_versions_failed", share_token=share_token, error=str(exc))
        versions = []

    content_format = (
        file.get("version_format") or file.get("content_format") or "markdown"
    )
    content_html = _render_content(file.get("content") or "", content_format)

    # Interactive HTML files (tools, dashboards) are rendered inside a sandboxed
    # iframe on this page via ``srcdoc`` so the tool works fully — scripts run in
    # an opaque, sandboxed origin with no access to teamshared cookies/parent
    # origin. This avoids the broken sanitized shell (which strips scripts/styles
    # but leaves their text behind) and needs no public bucket mirror.
    embed_interactive = content_format == "html"

    # For interactive HTML files, the sanitized shell on this page strips
    # <script>/<canvas>/<input>. If a bucket mirror is configured, surface the
    # direct CDN URL (which serves the raw, fully interactive HTML) so visitors
    # can open the working version in a standalone tab too.
    direct_url: str | None = None
    publisher = getattr(state.services, "file_publisher", None)
    if publisher and content_format == "html":
        try:
            direct_url = publisher.public_url(share_token)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("shared_file_direct_url_failed", share_token=share_token, error=str(exc))

    ctx = {
        "file": file,
        "content_html": content_html,
        "content_format": content_format,
        "embed_interactive": embed_interactive,
        "raw_html": file.get("content") or "" if embed_interactive else "",
        "direct_url": direct_url,
        "versions": versions,
        "current_version": file.get("version"),
        "is_latest": file.get("version") == file.get("current_version"),
        "share_token": share_token,
        "title": file.get("title") or "Shared file",
    }
    return _TEMPLATES.TemplateResponse(request, "file_public.html", ctx)
