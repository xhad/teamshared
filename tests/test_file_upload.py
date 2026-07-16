"""One-time file-upload: grant mint/consume, script generation, and the
``POST /v1/files/upload`` handler. Uses mocked services (no Postgres/Redis)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from teamshared.server.shared_files_upload import (
    MAX_UPLOAD_BYTES,
    build_upload_script,
    handle_shared_file_upload,
    mint_upload_grant,
    sniff_content_format,
)

_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_AGENT_ID = UUID("11111111-1111-1111-1111-1111111111aa")
_FILE_ID = UUID("22222222-2222-2222-2222-2222222222aa")


# ---------- sniff_content_format ----------

def test_sniff_explicit_html_wins() -> None:
    assert sniff_content_format("foo.md", "text/markdown", "html") == "html"


def test_sniff_auto_uses_extension() -> None:
    assert sniff_content_format("modeller.html", None, "auto") == "html"
    assert sniff_content_format("notes.md", None, "auto") == "markdown"


def test_sniff_auto_uses_content_type_when_no_ext() -> None:
    assert sniff_content_format(None, "text/html; charset=utf-8", "auto") == "html"
    assert sniff_content_format(None, "text/markdown", "auto") == "markdown"


def test_sniff_auto_defaults_to_markdown() -> None:
    assert sniff_content_format(None, None, "auto") == "markdown"


# ---------- build_upload_script ----------

def test_build_upload_script_embeds_token_url_and_self_deletes() -> None:
    script = build_upload_script(
        upload_url="https://teamshared.com/v1/files/upload",
        upload_token="tok-xyz",
        filename="modeller.html",
        publish=True,
    )
    assert "https://teamshared.com/v1/files/upload" in script
    assert "tok-xyz" in script
    assert "modeller.html" in script
    assert "os.remove(__file__)" in script
    assert script.startswith("#!/usr/bin/env python3")


# ---------- grant mint + pop ----------

def _services_with_working() -> tuple[MagicMock, list[dict[str, Any]]]:
    store: dict[str, str] = {}

    async def set_grant(token: str, payload: dict[str, Any], *, ttl: int = 600) -> None:
        import json
        store[token] = json.dumps(payload)

    async def pop_grant(token: str) -> dict[str, Any] | None:
        import json
        raw = store.pop(token, None)
        return json.loads(raw) if raw else None

    working = MagicMock()
    working.set_file_upload_grant = AsyncMock(side_effect=set_grant)
    working.pop_file_upload_grant = AsyncMock(side_effect=pop_grant)

    services = MagicMock()
    services.working = working
    return services, store


def test_mint_upload_grant_stores_and_pops() -> None:
    services, _ = _services_with_working()
    grant = asyncio.run(mint_upload_grant(
        services=services, org_id=_ORG, principal_id=_AGENT_ID, principal_type="agent",
        principal_display="cursor", principal_attribution="cursor",
        title="T", content_format="auto", filename="x.html", publish=False,
    ))
    assert grant["token"]
    popped = asyncio.run(services.working.pop_file_upload_grant(grant["token"]))
    assert popped is not None
    assert popped["title"] == "T"
    # single-use: second pop is None
    again = asyncio.run(services.working.pop_file_upload_grant(grant["token"]))
    assert again is None


# ---------- handle_shared_file_upload ----------

class _FakeRequest:
    def __init__(self, *, token: str | None, body: bytes, headers: dict[str, str]) -> None:
        self._token = token
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


def _services_for_handler(*, publish_returns: dict[str, Any] | None = None,
                          latest: dict[str, Any] | None = None) -> MagicMock:
    services, _ = _services_with_working()
    shared_files = MagicMock()
    shared_files.create = AsyncMock(return_value={
        "id": str(_FILE_ID), "title": "T", "version": 1, "content_format": "html",
    })
    shared_files.publish = AsyncMock(return_value=publish_returns or {
        "id": str(_FILE_ID), "share_token": "tok-share", "version": 1, "current_version": 1,
    })
    shared_files.get = AsyncMock(return_value=latest or {
        "id": str(_FILE_ID), "content": "<script>x</script>", "content_format": "html",
        "version": 1,
    })
    services.shared_files = shared_files
    audit = MagicMock()
    audit.record = AsyncMock()
    services.audit = audit
    return services


def test_handle_upload_creates_file_and_audits() -> None:
    services = _services_for_handler()
    # Mint a grant first.
    grant = asyncio.run(mint_upload_grant(
        services=services, org_id=_ORG, principal_id=_AGENT_ID, principal_type="agent",
        principal_display="cursor", principal_attribution="cursor",
        title="Modeller", content_format="auto", filename="modeller.html", publish=False,
    ))
    req = _FakeRequest(
        token=grant["token"], body=b"<html><script>1</script></html>",
        headers={"x-upload-token": grant["token"], "x-filename": "modeller.html",
                 "content-type": "text/html; charset=utf-8"},
    )
    resp = asyncio.run(handle_shared_file_upload(req, services))
    assert resp.status_code == 201
    import json
    payload = json.loads(resp.body)
    assert payload["file_id"] == str(_FILE_ID)
    assert payload["content_format"] == "html"
    services.shared_files.create.assert_awaited_once()
    services.audit.record.assert_awaited_once()
    assert services.audit.record.await_args.kwargs["action"] == "file.create_via_upload"


def test_handle_upload_missing_token_returns_401() -> None:
    services = _services_for_handler()
    req = _FakeRequest(token=None, body=b"x", headers={})
    resp = asyncio.run(handle_shared_file_upload(req, services))
    assert resp.status_code == 401


def test_handle_upload_invalid_token_returns_401() -> None:
    services = _services_for_handler()
    req = _FakeRequest(token="bogus", body=b"x",
                      headers={"x-upload-token": "bogus", "content-type": "text/html"})
    resp = asyncio.run(handle_shared_file_upload(req, services))
    assert resp.status_code == 401


def test_handle_upload_too_large_returns_413() -> None:
    services = _services_for_handler()
    grant = asyncio.run(mint_upload_grant(
        services=services, org_id=_ORG, principal_id=_AGENT_ID, principal_type="agent",
        principal_display="cursor", principal_attribution="cursor",
        title="T", content_format="html", filename="big.html", publish=False,
    ))
    req = _FakeRequest(token=grant["token"], body=b"a" * (MAX_UPLOAD_BYTES + 1),
                      headers={"x-upload-token": grant["token"], "content-type": "text/html"})
    resp = asyncio.run(handle_shared_file_upload(req, services))
    assert resp.status_code == 413


def test_handle_upload_empty_body_returns_400() -> None:
    services = _services_for_handler()
    grant = asyncio.run(mint_upload_grant(
        services=services, org_id=_ORG, principal_id=_AGENT_ID, principal_type="agent",
        principal_display="cursor", principal_attribution="cursor",
        title="T", content_format="html", filename="x.html", publish=False,
    ))
    req = _FakeRequest(token=grant["token"], body=b"   ",
                      headers={"x-upload-token": grant["token"], "content-type": "text/html"})
    resp = asyncio.run(handle_shared_file_upload(req, services))
    assert resp.status_code == 400


def test_handle_upload_publish_returns_public_urls() -> None:
    services = _services_for_handler(
        publish_returns={"id": str(_FILE_ID), "share_token": "tok-share", "version": 1, "current_version": 1},
        latest={"id": str(_FILE_ID), "content": "<script>x</script>", "content_format": "html", "version": 1},
    )
    publisher = MagicMock()
    publisher.publish_html = AsyncMock()
    publisher.public_url = MagicMock(return_value="https://files.example.test/tok-share/index.html")
    services.file_publisher = publisher

    grant = asyncio.run(mint_upload_grant(
        services=services, org_id=_ORG, principal_id=_AGENT_ID, principal_type="agent",
        principal_display="cursor", principal_attribution="cursor",
        title="Modeller", content_format="html", filename="modeller.html", publish=True,
    ))
    req = _FakeRequest(token=grant["token"], body=b"<script>x</script>",
                      headers={"x-upload-token": grant["token"], "x-filename": "modeller.html",
                               "content-type": "text/html"})
    resp = asyncio.run(handle_shared_file_upload(req, services))
    assert resp.status_code == 201
    import json
    payload = json.loads(resp.body)
    assert payload["share_token"] == "tok-share"
    assert payload["public_url"] == "/s/tok-share"
    assert payload["public_url_direct"] == "https://files.example.test/tok-share/index.html"
    # raw HTML mirrored verbatim (not sanitized)
    publisher.publish_html.assert_awaited_once()
    body_arg = publisher.publish_html.await_args.args[2]
    assert body_arg == "<script>x</script>"


def test_handle_upload_token_is_single_use() -> None:
    services = _services_for_handler()
    grant = asyncio.run(mint_upload_grant(
        services=services, org_id=_ORG, principal_id=_AGENT_ID, principal_type="agent",
        principal_display="cursor", principal_attribution="cursor",
        title="T", content_format="html", filename="x.html", publish=False,
    ))
    req1 = _FakeRequest(token=grant["token"], body=b"<p>hi</p>",
                       headers={"x-upload-token": grant["token"], "content-type": "text/html"})
    r1 = asyncio.run(handle_shared_file_upload(req1, services))
    assert r1.status_code == 201
    # second use of same token must fail
    req2 = _FakeRequest(token=grant["token"], body=b"<p>hi</p>",
                       headers={"x-upload-token": grant["token"], "content-type": "text/html"})
    r2 = asyncio.run(handle_shared_file_upload(req2, services))
    assert r2.status_code == 401
