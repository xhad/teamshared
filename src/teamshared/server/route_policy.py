"""HTTP route classification for auth and CI contract tests.

Every path the Starlette app serves must map to exactly one :class:`RouteClass`.
The outer :class:`teamshared.auth.BearerAuthMiddleware` skips bearer validation
for routes that authenticate elsewhere (console session, /v1 principal middleware)
or are intentionally public.
"""

from __future__ import annotations

from enum import Enum

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import ASGIApp


class RouteClass(str, Enum):
    PUBLIC_UNAUTH = "public_unauthenticated"
    PUBLIC_MINT = "public_mint"
    HEALTH_METRICS = "health_metrics"
    CONSOLE_SESSION = "console_session"
    API_V1 = "api_v1"
    MCP_BEARER = "mcp_bearer"


# Exact paths (no trailing slash normalization — Starlette paths are canonical).
_EXACT: dict[str, RouteClass] = {
    "/": RouteClass.PUBLIC_UNAUTH,
    "/favicon.ico": RouteClass.PUBLIC_UNAUTH,
    "/health": RouteClass.HEALTH_METRICS,
    "/metrics": RouteClass.HEALTH_METRICS,
    "/memory": RouteClass.PUBLIC_UNAUTH,
    "/get-token": RouteClass.PUBLIC_UNAUTH,
    "/install": RouteClass.PUBLIC_UNAUTH,
    "/install.sh": RouteClass.PUBLIC_UNAUTH,
    "/uninstall.sh": RouteClass.PUBLIC_UNAUTH,
    "/plugin/teamshared.tar.gz": RouteClass.PUBLIC_UNAUTH,
    "/tokens/mint": RouteClass.PUBLIC_MINT,
    "/tokens/invites": RouteClass.PUBLIC_MINT,
    "/state": RouteClass.MCP_BEARER,
    "/sessions/turns": RouteClass.MCP_BEARER,
}

# Longest-prefix wins among these (order matters for overlaps).
_PREFIX: tuple[tuple[str, RouteClass], ...] = (
    ("/mcp", RouteClass.MCP_BEARER),
    ("/v1", RouteClass.API_V1),
    ("/app", RouteClass.CONSOLE_SESSION),
    ("/login", RouteClass.CONSOLE_SESSION),
    ("/logout", RouteClass.CONSOLE_SESSION),
    ("/tokens/mint/", RouteClass.PUBLIC_MINT),
    ("/get-token/", RouteClass.PUBLIC_UNAUTH),
    ("/install/assets/", RouteClass.PUBLIC_UNAUTH),
    ("/install/plugin/", RouteClass.PUBLIC_UNAUTH),
)


def classify_path(path: str) -> RouteClass | None:
    """Return the auth class for ``path``, or ``None`` if unregistered."""
    if path in _EXACT:
        return _EXACT[path]
    for prefix, route_class in _PREFIX:
        if path.startswith(prefix):
            return route_class
    return None


def outer_middleware_skips_bearer(path: str) -> bool:
    """True when the outer bearer middleware should not require a token."""
    route_class = classify_path(path)
    if route_class is None:
        return False
    return route_class != RouteClass.MCP_BEARER


def iter_http_paths(app: ASGIApp) -> list[str]:
    """Collect route path patterns from a Starlette app (including mounts)."""
    if isinstance(app, Starlette):
        paths: list[str] = []
        for route in app.routes:
            paths.extend(_paths_from_route(route, ""))
        return sorted(set(paths))
    return []


def _paths_from_route(route: Mount | Route, parent: str) -> list[str]:
    if isinstance(route, Mount):
        prefix = parent + route.path.rstrip("/")
        child_paths: list[str] = [prefix or "/"]
        for child in route.routes:
            child_paths.extend(_paths_from_route(child, prefix))
        return child_paths
    if isinstance(route, Route):
        full = parent + route.path
        return [full or "/"]
    return []


def validate_app_routes(app: ASGIApp) -> list[str]:
    """Return paths that are not classified (empty list means OK)."""
    unclassified: list[str] = []
    for path in iter_http_paths(app):
        if classify_path(path) is None:
            unclassified.append(path)
    return unclassified
