"""MCP URL normalization for streamable HTTP clients.

Many MCP clients (including Cursor) POST to ``/mcp`` without a trailing slash.
Starlette's :class:`~starlette.routing.Mount` answers that with a **307** to
``/mcp/``, which drops the streamable HTTP session and surfaces
``Session not found`` on the follow-up request. Rewrite the path in-place
instead of redirecting.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class McpSlashMiddleware:
    """Rewrite ``/mcp`` → ``/mcp/`` before routing (no redirect)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            raw = scope.get("raw_path", b"/mcp")
            if raw == b"/mcp":
                scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)
