"""MCP path rewrite: ``/mcp`` must not 307 (breaks streamable HTTP sessions)."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from teamshared.server.mcp_path import McpSlashMiddleware


def test_mcp_without_trailing_slash_not_redirected() -> None:
    async def mcp_root(request):
        return PlainTextResponse(request.url.path)

    inner = Starlette(routes=[Route("/", mcp_root)])
    app = Starlette(
        routes=[Mount("/mcp", app=inner)],
        middleware=[Middleware(McpSlashMiddleware)],
    )
    with TestClient(app, follow_redirects=False) as client:
        resp = client.get("/mcp")
        assert resp.status_code == 200
        assert resp.text == "/mcp/"
        assert "location" not in resp.headers
