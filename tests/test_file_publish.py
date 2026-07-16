"""FilePublisher: S3-compatible bucket mirroring with a mocked boto3 client.

The boto3 S3 client is injected via ``client_factory`` so tests never touch the
network or require the boto3 package at import time.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.storage.bucket import FilePublisher, build_file_publisher


def _make_mock_client():
    client = MagicMock()
    client.put_object = MagicMock()
    paginator = MagicMock()
    page = {"Contents": [{"Key": "tok/v1.html"}, {"Key": "tok/index.html"}]}
    paginator.paginate.return_value = [page]
    client.get_paginator.return_value = paginator
    client.delete_objects = MagicMock()
    return client


def _publisher_with_mock_client():
    client = _make_mock_client()
    publisher = FilePublisher(
        endpoint="https://s3.example.test",
        bucket="files",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
        public_base_url="https://files.example.test",
        client_factory=lambda *a, **kw: client,
    )
    return publisher, client


def test_publish_html_puts_version_and_index() -> None:
    publisher, client = _publisher_with_mock_client()
    asyncio.run(publisher.publish_html("tok", 3, "<h1>hi</h1>"))

    calls = client.put_object.call_args_list
    assert len(calls) == 2
    keys = [c.kwargs["Key"] for c in calls]
    assert "tok/v3.html" in keys
    assert "tok/index.html" in keys
    # Both bodies are the utf-8 encoded html.
    for c in calls:
        assert c.kwargs["Body"] == b"<h1>hi</h1>"
        assert c.kwargs["ContentType"] == "text/html; charset=utf-8"


def test_unpublish_deletes_prefix() -> None:
    publisher, client = _publisher_with_mock_client()
    asyncio.run(publisher.unpublish("tok"))

    client.get_paginator.assert_called_once_with("list_objects_v2")
    paginator = client.get_paginator.return_value
    paginator.paginate.assert_called_once_with(Bucket="files", Prefix="tok/")
    client.delete_objects.assert_called_once()
    delete_payload = client.delete_objects.call_args.kwargs["Delete"]
    assert delete_payload["Objects"] == [
        {"Key": "tok/v1.html"}, {"Key": "tok/index.html"}
    ]


def test_public_url_uses_base_and_version() -> None:
    publisher, _ = _publisher_with_mock_client()
    assert publisher.public_url("tok") == "https://files.example.test/tok/index.html"
    assert publisher.public_url("tok", 2) == "https://files.example.test/tok/v2.html"


def test_public_url_none_without_base() -> None:
    client = _make_mock_client()
    publisher = FilePublisher(
        endpoint="https://s3.example.test",
        bucket="files",
        access_key="ak",
        secret_key="sk",
        client_factory=lambda *a, **kw: client,
    )
    assert publisher.public_url("tok") is None
    assert publisher.public_url("tok", 2) is None


def test_build_file_publisher_none_when_unconfigured() -> None:
    settings = MagicMock()
    settings.object_storage_endpoint = None
    settings.object_storage_bucket = "b"
    settings.object_storage_access_key = "k"
    settings.object_storage_secret_key = "s"
    settings.object_storage_region = None
    settings.object_storage_public_base_url = None
    assert build_file_publisher(settings) is None


def test_build_file_publisher_builds_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_mock_client()
    monkeypatch.setattr(
        "teamshared.storage.bucket._client_factory",
        lambda *a, **kw: client,
    )
    settings = MagicMock()
    settings.object_storage_endpoint = "https://s3.example.test"
    settings.object_storage_bucket = "files"
    settings.object_storage_access_key = "ak"
    settings.object_storage_secret_key = "sk"
    settings.object_storage_region = "us-east-1"
    settings.object_storage_public_base_url = "https://files.example.test"
    publisher = build_file_publisher(settings)
    assert publisher is not None
    assert publisher.public_base_url == "https://files.example.test"


def test_build_file_publisher_partial_config_returns_none() -> None:
    settings = MagicMock()
    settings.object_storage_endpoint = "https://s3.example.test"
    settings.object_storage_bucket = None  # missing bucket
    settings.object_storage_access_key = "ak"
    settings.object_storage_secret_key = "sk"
    settings.object_storage_region = None
    settings.object_storage_public_base_url = None
    assert build_file_publisher(settings) is None


# --- Facade file_publish bucket mirror: raw HTML vs sanitized markdown ---
#
# Interactive HTML files (script/canvas/inputs) must be mirrored VERBATIM to the
# bucket so the direct CDN URL serves a working tool; the /s/{token} route
# keeps rendering the sanitized shell. Markdown files are rendered to safe HTML
# at mirror time.

from uuid import UUID  # noqa: E402

from teamshared.identity.principal import Principal  # noqa: E402
from teamshared.memory.facade import MemoryFacade  # noqa: E402

_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_AGENT_ID = UUID("11111111-1111-1111-1111-1111111111aa")
_FILE_ID = UUID("22222222-2222-2222-2222-2222222222aa")


def _principal() -> Principal:
    return Principal(
        org_id=_ORG, type="agent", id=_AGENT_ID, display="cursor", roles=("agent",)
    )


def _facade_for_publish(*, content: str, content_format: str) -> tuple[MemoryFacade, MagicMock]:
    publisher = MagicMock()
    publisher.publish_html = AsyncMock()
    publisher.public_url = MagicMock(return_value="https://files.example.test/tok/index.html")

    shared_files = MagicMock()
    shared_files.publish = AsyncMock(
        return_value={
            "id": str(_FILE_ID),
            "share_token": "tok",
            "version": 1,
            "current_version": 1,
            "content_format": content_format,
            "visibility": "published",
            "status": "active",
        }
    )
    shared_files.get = AsyncMock(
        return_value={
            "id": str(_FILE_ID),
            "share_token": "tok",
            "version": 1,
            "current_version": 1,
            "content": content,
            "content_format": content_format,
        }
    )

    audit = MagicMock()
    audit.record = AsyncMock()
    services = MagicMock()
    services.tenant_db = MagicMock()
    auth_ctx = MagicMock()
    auth_ctx.require = AsyncMock()
    services.authorizer = MagicMock(return_value=auth_ctx)
    services.audit = audit
    services.shared_files = shared_files
    services.file_publisher = publisher

    facade = MemoryFacade(
        services=services,
        resolver=MagicMock(),
        working=MagicMock(),
        agent_state=MagicMock(),
        procedural=MagicMock(),
        skills=MagicMock(),
        strategic=MagicMock(),
        graph=None,
    )
    return facade, publisher


async def test_file_publish_mirrors_raw_html_verbatim() -> None:
    raw = "<script>const x=1</script><canvas></canvas><input>"
    facade, publisher = _facade_for_publish(content=raw, content_format="html")
    out = await facade.file_publish(_principal(), file_id=str(_FILE_ID))
    publisher.publish_html.assert_awaited_once()
    body = publisher.publish_html.await_args.args[2]
    assert body == raw, "interactive HTML must be mirrored verbatim (not sanitized)"
    assert out["public_url_direct"] == "https://files.example.test/tok/index.html"


async def test_file_publish_mirrors_markdown_as_sanitized_html() -> None:
    md = "# Title\n\n[link](javascript:alert(1))\n\n<iframe>x</iframe>"
    facade, publisher = _facade_for_publish(content=md, content_format="markdown")
    await facade.file_publish(_principal(), file_id=str(_FILE_ID))
    publisher.publish_html.assert_awaited_once()
    body = publisher.publish_html.await_args.args[2]
    # markdown rendered to HTML, then sanitized: iframe dropped, js: href dropped.
    assert "<iframe>" not in body
    assert "javascript:" not in body
    assert "<h1>" in body or "<h1" in body


def test_serialize_file_adds_public_url_from_slug() -> None:
    from teamshared.memory.facade import _serialize_file

    published = {
        "id": "f1", "title": "T", "visibility": "published",
        "slug": "my-tool", "share_token": "11111111-1111-1111-1111-111111111111",
    }
    assert _serialize_file(published)["public_url"] == "/s/my-tool"

    # Falls back to share_token when no slug.
    published_no_slug = dict(published)
    published_no_slug["slug"] = None
    assert _serialize_file(published_no_slug)["public_url"] == "/s/11111111-1111-1111-1111-111111111111"

    # Private files have no public URL.
    private = dict(published)
    private["visibility"] = "private"
    assert _serialize_file(private)["public_url"] is None

    assert _serialize_file(None) == {}
