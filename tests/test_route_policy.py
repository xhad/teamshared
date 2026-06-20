"""HTTP route classification contract."""

from __future__ import annotations

import pytest

from teamshared.server.app import build_http_app
from teamshared.server.route_policy import (
    RouteClass,
    classify_path,
    iter_http_paths,
    outer_middleware_requires_bearer,
    outer_middleware_skips_bearer,
    validate_app_routes,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", RouteClass.HEALTH_METRICS),
        ("/memory", RouteClass.PUBLIC_UNAUTH),
        ("/tokens/mint", RouteClass.PUBLIC_MINT),
        ("/tokens/mint/abc/cursor", RouteClass.PUBLIC_MINT),
        ("/mcp", RouteClass.MCP_BEARER),
        ("/mcp/tools/list", RouteClass.MCP_BEARER),
        ("/state", RouteClass.MCP_BEARER),
        ("/llm/prepare", RouteClass.MCP_BEARER),
        ("/tools/normalize", RouteClass.MCP_BEARER),
        ("/v1/memory/search", RouteClass.API_V1),
        ("/app/wiki", RouteClass.CONSOLE_SESSION),
        ("/login/verify", RouteClass.CONSOLE_SESSION),
    ],
)
def test_classify_path(path: str, expected: RouteClass) -> None:
    assert classify_path(path) == expected


@pytest.mark.parametrize(
    ("path", "skips"),
    [
        ("/health", True),
        ("/mcp/foo", False),
        ("/state", False),
        ("/v1/orgs", True),
        ("/app/memory", True),
    ],
)
def test_outer_middleware_skips_bearer(path: str, skips: bool) -> None:
    assert outer_middleware_skips_bearer(path) is skips
    assert outer_middleware_requires_bearer(path) is (not skips)


def test_only_mcp_bearer_class_requires_outer_bearer() -> None:
    for route_class in RouteClass:
        assert route_class.skips_outer_bearer() == (route_class != RouteClass.MCP_BEARER)


def test_unclassified_path_requires_bearer() -> None:
    assert classify_path("/totally-unknown") is None
    assert outer_middleware_skips_bearer("/totally-unknown") is False
    assert outer_middleware_requires_bearer("/totally-unknown") is True


def test_build_http_app_routes_are_classified() -> None:
    app = build_http_app()
    unclassified = validate_app_routes(app)
    assert unclassified == [], f"unclassified routes: {unclassified}"


def test_every_registered_path_matches_skip_policy() -> None:
    """Bearer skip/require must follow RouteClass.skips_outer_bearer for all routes."""
    app = build_http_app()
    for path in iter_http_paths(app):
        route_class = classify_path(path)
        assert route_class is not None, path
        assert outer_middleware_skips_bearer(path) == route_class.skips_outer_bearer(), path
