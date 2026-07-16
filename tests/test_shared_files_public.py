"""Public shared-file view (``GET /s/{share_token}``).

Interactive HTML files render inside a sandboxed ``srcdoc`` iframe so the tool
works fully (scripts run in an opaque origin, isolated from teamshared). Markdown
renders through the allowlist sanitizer. A configured bucket publisher surfaces a
"Standalone version" link to the raw CDN copy. The route accepts either a UUID
share_token or a human-readable slug.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.server.shared_files_public import handle_shared_file_view

_TOKEN = "11111111-1111-1111-1111-111111111111"


def _state(*, shared_files, file_publisher=None):
    services = MagicMock()
    services.shared_files = shared_files
    services.file_publisher = file_publisher
    state = MagicMock()
    state.services = services
    return state


def _app(state) -> Starlette:
    async def view(request):
        return await handle_shared_file_view(request, state)

    return Starlette(routes=[Route("/s/{share_token}", view, methods=["GET"])])


def _shared_mock(*, by_token=None, by_slug=None, versions_token=None, versions_slug=None):
    """A SharedFileStore mock with both token and slug paths wired as AsyncMocks."""
    shared = MagicMock()
    shared.get_published_by_token = AsyncMock(return_value=by_token)
    shared.get_published_by_slug = AsyncMock(return_value=by_slug)
    shared.get_published_version = AsyncMock(return_value=None)
    shared.get_published_version_by_slug = AsyncMock(return_value=None)
    shared.list_published_versions = AsyncMock(return_value=versions_token or [])
    shared.list_published_versions_by_slug = AsyncMock(return_value=versions_slug or [])
    return shared


def _html_file(content: str, *, content_format: str = "html", share_token=None) -> dict:
    d = {
        "id": "f1",
        "title": "Tool",
        "author_label": "cursor",
        "content": content,
        "content_format": content_format,
        "version": 1,
        "current_version": 1,
    }
    if share_token:
        d["share_token"] = share_token
    return d


def test_html_file_renders_in_sandboxed_iframe_via_slug() -> None:
    shared = _shared_mock(
        by_slug=_html_file("<script>alert(1)</script><h1>Tool</h1>", share_token=_TOKEN),
    )
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get("/s/my-tool")
    assert r.status_code == 200
    body = r.text
    assert "<iframe" in body
    assert 'srcdoc="' in body
    assert 'sandbox="allow-scripts' in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert(1)</script>" not in body
    shared.get_published_by_slug.assert_awaited_once_with("my-tool")


def test_html_file_renders_in_sandboxed_iframe_via_token() -> None:
    shared = _shared_mock(
        by_token=_html_file("<h1>Tool</h1>", content_format="html", share_token=_TOKEN),
    )
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get(f"/s/{_TOKEN}")
    assert r.status_code == 200
    assert "<iframe" in r.text
    shared.get_published_by_token.assert_awaited_once_with(_TOKEN)


def test_markdown_file_renders_sanitized_no_iframe() -> None:
    shared = _shared_mock(
        by_slug=_html_file("# Hi\n\n**bold**", content_format="markdown"),
    )
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get("/s/my-tool")
    assert r.status_code == 200
    body = r.text
    assert "<strong>bold</strong>" in body
    assert "<iframe" not in body


def test_html_file_with_publisher_shows_standalone_banner() -> None:
    shared = _shared_mock(
        by_slug=_html_file("<h1>Tool</h1>", share_token=_TOKEN),
    )
    publisher = MagicMock()
    publisher.public_url = MagicMock(return_value="https://cdn.example.test/tok/index.html")
    client = TestClient(_app(_state(shared_files=shared, file_publisher=publisher)))
    r = client.get("/s/my-tool")
    assert r.status_code == 200
    body = r.text
    assert "<iframe" in body
    assert "Standalone version" in body
    assert "https://cdn.example.test/tok/index.html" in body
    publisher.public_url.assert_called_once_with(_TOKEN)


def test_missing_file_returns_404() -> None:
    shared = _shared_mock(by_slug=None)
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get("/s/no-such-slug")
    assert r.status_code == 404
