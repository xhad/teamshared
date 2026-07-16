"""Public shared-file view (``GET /s/{share_token}``).

Interactive HTML files render inside a sandboxed ``srcdoc`` iframe so the tool
works fully (scripts run in an opaque origin, isolated from teamshared). Markdown
renders through the allowlist sanitizer. A configured bucket publisher surfaces a
"Standalone version" link to the raw CDN copy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.server.shared_files_public import handle_shared_file_view


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


def _html_file(content: str, *, content_format: str = "html") -> dict:
    return {
        "id": "f1",
        "title": "Tool",
        "author_label": "cursor",
        "content": content,
        "content_format": content_format,
        "version": 1,
        "current_version": 1,
    }


def test_html_file_renders_in_sandboxed_iframe() -> None:
    shared = MagicMock()
    shared.get_published_by_token = AsyncMock(
        return_value=_html_file("<script>alert(1)</script><h1>Tool</h1>")
    )
    shared.list_published_versions = AsyncMock(return_value=[])
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get("/s/tok")
    assert r.status_code == 200
    body = r.text
    # Sandboxed iframe with scripts allowed (opaque origin, no same-origin).
    assert "<iframe" in body
    assert 'srcdoc="' in body
    assert 'sandbox="allow-scripts' in body
    # Raw <script> tag is escaped inside the srcdoc attribute — not a live tag
    # on the host page.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert(1)</script>" not in body


def test_markdown_file_renders_sanitized_no_iframe() -> None:
    shared = MagicMock()
    shared.get_published_by_token = AsyncMock(
        return_value=_html_file("# Hi\n\n**bold**", content_format="markdown")
    )
    shared.list_published_versions = AsyncMock(return_value=[])
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get("/s/tok")
    assert r.status_code == 200
    body = r.text
    assert "<strong>bold</strong>" in body
    assert "<iframe" not in body


def test_html_file_with_publisher_shows_standalone_banner() -> None:
    shared = MagicMock()
    shared.get_published_by_token = AsyncMock(
        return_value=_html_file("<h1>Tool</h1>")
    )
    shared.list_published_versions = AsyncMock(return_value=[])
    publisher = MagicMock()
    publisher.public_url = MagicMock(return_value="https://cdn.example.test/tok/index.html")
    client = TestClient(_app(_state(shared_files=shared, file_publisher=publisher)))
    r = client.get("/s/tok")
    assert r.status_code == 200
    body = r.text
    assert "<iframe" in body  # iframe still renders the tool inline
    assert "Standalone version" in body
    assert "https://cdn.example.test/tok/index.html" in body


def test_missing_file_returns_404() -> None:
    shared = MagicMock()
    shared.get_published_by_token = AsyncMock(return_value=None)
    shared.list_published_versions = AsyncMock(return_value=[])
    client = TestClient(_app(_state(shared_files=shared, file_publisher=None)))
    r = client.get("/s/tok")
    assert r.status_code == 404
