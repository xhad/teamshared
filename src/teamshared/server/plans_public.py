"""Public plan view handler for ``GET /plan/{share_token}``.

No-auth (whitelisted as ``PUBLIC_UNAUTH`` in :mod:`teamshared.server.route_policy`).
Reads a published plan + its versions through the SECURITY DEFINER functions in
:mod:`teamshared.memory.plans` (over an RLS-less ``admin()`` connection) and
renders a standalone Jinja2 template with a collapsible version-history sidebar.

Content is rendered through the allowlist sanitizer
(:func:`teamshared.server.markdown_safe.render_markdown_safe` for markdown,
:func:`sanitize_html` for raw HTML) so agent-authored plans can never inject
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


async def handle_plan_view(request: Request, state: Any) -> Response:
    """Render a published plan at ``/plan/{share_token}``.

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
            plan = await state.services.plans.get_published_version(
                share_token, requested_version
            )
        else:
            plan = await state.services.plans.get_published_by_token(share_token)
    except Exception as exc:
        log.warning("plan_view_failed", share_token=share_token, error=str(exc))
        return HTMLResponse(
            "<h1>Plan unavailable</h1><p>This plan could not be loaded.</p>",
            status_code=503,
        )

    if plan is None:
        return HTMLResponse(
            "<h1>Plan not found</h1>"
            "<p>This plan is private, unpublished, or has been deleted.</p>",
            status_code=404,
        )

    try:
        versions = await state.services.plans.list_published_versions(share_token)
    except Exception as exc:
        log.warning("plan_versions_failed", share_token=share_token, error=str(exc))
        versions = []

    content_html = _render_content(
        plan.get("content") or "", plan.get("version_format") or plan.get("content_format") or "markdown"
    )
    ctx = {
        "plan": plan,
        "content_html": content_html,
        "versions": versions,
        "current_version": plan.get("version"),
        "is_latest": plan.get("version") == plan.get("current_version"),
        "share_token": share_token,
        "title": plan.get("title") or "Plan",
    }
    return _TEMPLATES.TemplateResponse(request, "plan_public.html", ctx)
