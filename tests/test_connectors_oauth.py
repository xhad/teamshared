"""OAuth integration tests: vault bundle, oauth helpers (mocked httpx), and
ConnectorService OAuth paths (create_oauth_connection, refresh_if_needed, send,
search) with mocked adapters and a fake TenantDb.

Unit-level (no real Postgres/Redis): mirrors the style of test_connectors.py.
"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teamshared.connectors.adapters import GmailConnector, SlackConnector
from teamshared.connectors.base import SourceDoc, SyncResult
from teamshared.connectors.oauth import (
    GMAIL_SCOPES,
    SLACK_SCOPES,
    build_authorize_url,
    exchange_code,
    refresh_access_token,
)
from teamshared.connectors.vault import TokenBundle, TokenVault


# --- vault bundle -----------------------------------------------------------


def test_vault_bundle_roundtrip() -> None:
    key = base64.b64encode(os.urandom(32)).decode()
    vault = TokenVault(key)
    bundle = TokenBundle(
        access_token="ya29.access",
        refresh_token="1//refresh",
        token_type="Bearer",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        expires_at=(datetime.now(UTC) + timedelta(seconds=3600)).isoformat(),
    )
    ct, nonce, key_id = vault.encrypt_bundle(bundle)
    out = vault.decrypt_bundle(ct, nonce)
    assert out.access_token == "ya29.access"
    assert out.refresh_token == "1//refresh"
    assert out.scope == bundle.scope
    assert key_id == vault.key_id


def test_bundle_is_expired() -> None:
    past = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    bundle = TokenBundle(access_token="x", expires_at=past)
    assert bundle.is_expired() is True
    future = (datetime.now(UTC) + timedelta(seconds=600)).isoformat()
    assert TokenBundle(access_token="x", expires_at=future).is_expired() is False
    # No expiry → never expired.
    assert TokenBundle(access_token="x").is_expired() is False


# --- oauth helpers ----------------------------------------------------------


def test_build_authorize_url_gmail() -> None:
    url = build_authorize_url(
        "gmail", client_id="cid", redirect_uri="https://app/cb", state="st123",
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Fapp%2Fcb" in url
    assert "state=st123" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    # Scopes are space-joined then URL-encoded (spaces become +, slashes %2F).
    assert "gmail.readonly" in url and "gmail.send" in url


def test_build_authorize_url_slack() -> None:
    url = build_authorize_url(
        "slack", client_id="cid", redirect_uri="https://app/cb", state="st456",
    )
    assert url.startswith("https://slack.com/oauth/v2/authorize?")
    assert "client_id=cid" in url
    assert "state=st456" in url
    # Scopes are comma-joined then URL-encoded (commas %2C, colons %3A).
    assert "channels%3Ahistory" in url and "chat%3Awrite" in url


def test_build_authorize_url_unknown_kind() -> None:
    with pytest.raises(ValueError):
        build_authorize_url("dropbox", client_id="x", redirect_uri="y", state="z")


def test_exchange_code_gmail_mocked() -> None:
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "access_token": "ya29.abc",
        "refresh_token": "1//r",
        "token_type": "Bearer",
        "scope": " ".join(GMAIL_SCOPES),
        "expires_in": 3600,
    })
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=fake_resp)
    with patch("teamshared.connectors.oauth.httpx.AsyncClient", return_value=client):
        bundle = asyncio_run(exchange_code(
            "gmail", code="the-code", client_id="cid",
            client_secret="sec", redirect_uri="https://app/cb",
        ))
    assert bundle.access_token == "ya29.abc"
    assert bundle.refresh_token == "1//r"
    assert bundle.token_type == "Bearer"
    assert bundle.expires_at is not None


def test_exchange_code_slack_mocked() -> None:
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "ok": True,
        "access_token": "xoxb-app",
        "scope": ",".join(SLACK_SCOPES),
        "authed_user": {
            "access_token": "xoxp-user",
            "refresh_token": "xoxr-1",
            "scope": ",".join(SLACK_SCOPES),
            "expires_in": 43200,
        },
    })
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=fake_resp)
    with patch("teamshared.connectors.oauth.httpx.AsyncClient", return_value=client):
        bundle = asyncio_run(exchange_code(
            "slack", code="c", client_id="cid", client_secret="sec",
            redirect_uri="https://app/cb",
        ))
    assert bundle.access_token == "xoxp-user"
    assert bundle.refresh_token == "xoxr-1"
    assert bundle.expires_at is not None


def test_refresh_access_token_slack_rotation_mocked() -> None:
    """Slack returns a NEW refresh token on each refresh (token rotation)."""
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "ok": True,
        "access_token": "xoxp-new",
        "refresh_token": "xoxr-2",
        "scope": ",".join(SLACK_SCOPES),
        "expires_in": 43200,
    })
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=fake_resp)
    with patch("teamshared.connectors.oauth.httpx.AsyncClient", return_value=client):
        bundle = asyncio_run(refresh_access_token(
            "slack", refresh_token="xoxr-1", client_id="cid", client_secret="sec",
        ))
    assert bundle.access_token == "xoxp-new"
    # The new refresh token supersedes the old one.
    assert bundle.refresh_token == "xoxr-2"


# --- ConnectorService OAuth paths (mocked DB) -------------------------------


class _Conn:
    def __init__(self, row_map: dict[str, object]) -> None:
        self._row_map = row_map

    async def execute(self, sql: str, params: object = None):
        cur = MagicMock()
        # Return the canned row for the first SELECT that matches a key.
        for key, row in self._row_map.items():
            if key in sql:
                cur.fetchone = AsyncMock(return_value=row)
                cur.fetchall = AsyncMock(return_value=[])
                cur.rowcount = 1
                return cur
        cur.fetchone = AsyncMock(return_value=None)
        cur.fetchall = AsyncMock(return_value=[])
        cur.rowcount = 0
        return cur


class _OrgCM:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _make_service(row_map: dict[str, object], *, settings: SimpleNamespace | None = None):
    from teamshared.connectors.service import ConnectorService
    from teamshared.memory.request_context import RequestContext

    tenant_db = MagicMock()
    tenant_db.org = MagicMock(return_value=_OrgCM(_Conn(row_map)))
    vault = TokenVault(None)
    audit = MagicMock()
    audit.record = AsyncMock()
    ingestion = MagicMock()
    ingestion.ingest = AsyncMock(return_value=SimpleNamespace(status="active", memory_id=uuid.uuid4()))
    svc = ConnectorService(
        tenant_db, vault, ingestion_factory=lambda: ingestion, audit=audit,
        settings=settings or SimpleNamespace(
            gmail_client_id="cid", gmail_client_secret="sec",
            slack_client_id="cid", slack_client_secret="sec",
        ),
    )
    return svc, ingestion


def _principal(account_id: uuid.UUID | None = None):
    from teamshared.identity.principal import Principal
    return Principal(
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        type="user", id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        account_id=account_id,
        display="owner@example.com",
    )


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def test_create_oauth_connection_stores_bundle() -> None:
    row_map = {
        "INSERT INTO connectors": (uuid.uuid4(),),
        "INSERT INTO connector_tokens": None,
        "UPDATE connectors SET status": None,
    }
    svc, ingestion = _make_service(row_map)
    ctx = SimpleNamespace(
        principal=_principal(account_id=uuid.uuid4()),
        db=svc.db, authorizer=SimpleNamespace(require=AsyncMock()),
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    bundle = TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=None)
    cid = asyncio_run(svc.create_oauth_connection(
        ctx, kind="gmail", name="gmail-owner", config={}, bundle=bundle,
    ))
    assert isinstance(cid, uuid.UUID)


def test_refresh_if_needed_skips_when_not_expired() -> None:
    future = (datetime.now(UTC) + timedelta(seconds=3600)).isoformat()
    bundle = TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=future)
    row_map = {
        "SELECT id, kind, name, status, config, account_id": (
            uuid.uuid4(), "gmail", "gmail-owner", "connected", {}, None,
        ),
        "SELECT ciphertext, nonce": (b"x", b"y"),
    }
    svc, _ = _make_service(row_map)
    # decrypt_bundle is called on the vault; patch it to return our bundle.
    svc.vault.decrypt_bundle = MagicMock(return_value=bundle)
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db,
        authorizer=SimpleNamespace(require=AsyncMock()),
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    out = asyncio_run(svc.refresh_if_needed(ctx, uuid.uuid4()))
    assert out is bundle  # unchanged, no refresh attempted


def test_refresh_if_needed_refreshes_expired() -> None:
    past = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    bundle = TokenBundle(access_token="ya29-old", refresh_token="1//r", expires_at=past)
    row_map = {
        "SELECT id, kind, name, status, config, account_id": (
            uuid.uuid4(), "gmail", "gmail-owner", "connected", {}, None,
        ),
        "SELECT ciphertext, nonce": (b"x", b"y"),
        "INSERT INTO connector_tokens": None,
        "UPDATE connectors SET status": None,
    }
    svc, _ = _make_service(row_map)
    svc.vault.decrypt_bundle = MagicMock(return_value=bundle)
    new_bundle = TokenBundle(
        access_token="ya29-new", refresh_token="1//r",
        expires_at=(datetime.now(UTC) + timedelta(seconds=3600)).isoformat(),
    )
    with patch("teamshared.connectors.oauth.refresh_access_token", new=AsyncMock(return_value=new_bundle)):
        ctx = SimpleNamespace(
            principal=_principal(), db=svc.db,
            authorizer=SimpleNamespace(require=AsyncMock()),
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            request_id="req",
        )
        out = asyncio_run(svc.refresh_if_needed(ctx, uuid.uuid4()))
    assert out.access_token == "ya29-new"


def test_send_gmail_writes_episodic_event() -> None:
    row_map = {
        "SELECT id, kind, name, status, config, account_id": (
            uuid.uuid4(), "gmail", "gmail-owner", "connected", {}, None,
        ),
        "SELECT ciphertext, nonce": (b"x", b"y"),
    }
    svc, ingestion = _make_service(row_map)
    future = (datetime.now(UTC) + timedelta(seconds=3600)).isoformat()
    bundle = TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=future)
    svc.vault.decrypt_bundle = MagicMock(return_value=bundle)
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db,
        authorizer=SimpleNamespace(require=AsyncMock()),
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    with patch.object(GmailConnector, "send", new=AsyncMock(return_value={"id": "msg-1"})):
        result = asyncio_run(svc.send(
            ctx, uuid.uuid4(), kind="gmail", to="x@y.test",
            subject="hi", body="hello",
        ))
    assert result["sent"] is True
    # An episodic event was ingested.
    assert ingestion.ingest.await_count == 1
    call = ingestion.ingest.await_args
    assert call.kwargs.get("kind") == "event"
    assert "integration" in call.kwargs.get("tags", [])


def test_search_gmail_calls_list_messages() -> None:
    row_map = {
        "SELECT id, kind, name, status, config, account_id": (
            uuid.uuid4(), "gmail", "gmail-owner", "connected", {}, None,
        ),
        "SELECT ciphertext, nonce": (b"x", b"y"),
    }
    svc, _ = _make_service(row_map)
    future = (datetime.now(UTC) + timedelta(seconds=3600)).isoformat()
    bundle = TokenBundle(access_token="ya29", refresh_token="1//r", expires_at=future)
    svc.vault.decrypt_bundle = MagicMock(return_value=bundle)
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db,
        authorizer=SimpleNamespace(require=AsyncMock()),
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    with patch.object(
        GmailConnector, "list_messages",
        new=AsyncMock(return_value=[{"id": "m1", "subject": "hello"}]),
    ):
        hits = asyncio_run(svc.search(ctx, uuid.uuid4(), query="hello", max_results=5))
    assert hits == [{"id": "m1", "subject": "hello"}]


# --- adapter unit tests (mocked httpx) ---------------------------------------


def test_gmail_msg_to_doc() -> None:
    adapter = GmailConnector({})
    msg = {
        "id": "abc",
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "a@x.test"},
                {"name": "Subject", "value": "Hello"},
                {"name": "To", "value": "me@x.test"},
            ],
            "body": {"data": "aGVsbG8="},  # "hello"
        },
    }
    doc = adapter._msg_to_doc(msg)
    assert doc.external_id == "gmail:abc"
    assert doc.title == "Hello"
    assert "Hello" in doc.content
    assert "a@x.test" in doc.content
    assert doc.uri.endswith("#inbox/abc")
    assert doc.acl["from"] == "a@x.test"


def test_slack_post_message_mocked() -> None:
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={"ok": True, "ts": "1700000000.1"})
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=fake_resp)
    adapter = SlackConnector({})
    with patch("teamshared.connectors.adapters.httpx.AsyncClient", return_value=client):
        out = asyncio_run(adapter.post_message("xoxb", "C123", "hi", thread_ts="1699999999.0"))
    assert out["ok"] is True
    sent_body = client.post.await_args.kwargs["json"]
    assert sent_body["channel"] == "C123"
    assert sent_body["thread_ts"] == "1699999999.0"


def test_slack_fetch_without_channel_lists_conversations() -> None:
    """OAuth connections have empty config — fetch must list channels, not KeyError."""
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json = MagicMock(return_value={
        "ok": True,
        "channels": [{"id": "C1", "name": "general"}, {"id": "C2", "name": "eng"}],
    })
    hist_resp = MagicMock()
    hist_resp.raise_for_status = MagicMock()
    hist_resp.json = MagicMock(return_value={
        "ok": True,
        "messages": [
            {"ts": "1700000000.1", "text": "hello from general", "user": "U1"},
        ],
    })
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=[list_resp, hist_resp, hist_resp])
    adapter = SlackConnector({})  # no default channel
    with patch("teamshared.connectors.adapters.httpx.AsyncClient", return_value=client):
        result = asyncio_run(adapter.fetch("xoxp-tok", None))
    assert len(result.documents) >= 1
    assert result.documents[0].external_id.startswith("C1:")
    assert "hello" in result.documents[0].content
    # First call is conversations.list
    first_url = client.get.await_args_list[0].args[0]
    assert "conversations.list" in first_url


def test_slack_fetch_with_channel_skips_list() -> None:
    hist_resp = MagicMock()
    hist_resp.raise_for_status = MagicMock()
    hist_resp.json = MagicMock(return_value={
        "ok": True,
        "messages": [{"ts": "1.0", "text": "pinned channel msg", "user": "U1"}],
    })
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=hist_resp)
    adapter = SlackConnector({"channel": "C99"})
    with patch("teamshared.connectors.adapters.httpx.AsyncClient", return_value=client):
        result = asyncio_run(adapter.fetch("xoxp-tok", None))
    assert len(result.documents) == 1
    assert result.documents[0].external_id == "C99:1.0"
    assert client.get.await_count == 1
    assert "conversations.history" in client.get.await_args.args[0]


def test_slack_list_messages_filters_substring() -> None:
    adapter = SlackConnector({})
    docs = [
        SourceDoc(external_id="C1:1", content="deploy the app", acl={"channel": "C1"},
                  metadata={"channel_name": "eng"}),
        SourceDoc(external_id="C1:2", content="lunch plans", acl={"channel": "C1"},
                  metadata={"channel_name": "eng"}),
    ]
    with patch.object(
        adapter, "fetch", new=AsyncMock(return_value=SyncResult(documents=docs, next_cursor=None))
    ):
        hits = asyncio_run(adapter.list_messages("tok", "deploy", max_results=5))
    assert len(hits) == 1
    assert hits[0]["id"] == "C1:1"
    assert hits[0]["channel_name"] == "eng"


# --- Agent RBAC: memory:read/create, not connector:manage -------------------


def _tracking_authorizer(*allowed: str):
    """Authorizer stub that records required perms and enforces ``allowed``."""
    from teamshared.identity.rbac import PermissionDenied

    required: list[str] = []

    async def require(principal, permission: str) -> None:
        required.append(permission)
        if permission not in allowed:
            raise PermissionDenied(permission, principal)

    return SimpleNamespace(require=require, required=required)


def test_list_connectors_allows_memory_read_agent() -> None:
    """Agents have memory:read, not connector:manage — list must succeed."""
    from teamshared.identity.rbac import Permissions

    cid = uuid.uuid4()
    row_map = {
        "SELECT id, kind, name, status, created_at, account_id": None,
    }
    # _Conn returns fetchall=[] by default; override via a custom path.
    svc, _ = _make_service(row_map)
    # Make list_connectors' SELECT return one row via fetchall.
    conn = svc.db.org.return_value  # _OrgCM

    async def execute(sql: str, params: object = None):
        cur = MagicMock()
        if "SELECT id, kind, name, status, created_at, account_id" in sql:
            cur.fetchall = AsyncMock(
                return_value=[
                    (cid, "slack", "slack-me", "connected", datetime.now(UTC), None),
                ]
            )
        else:
            cur.fetchall = AsyncMock(return_value=[])
        cur.fetchone = AsyncMock(return_value=None)
        cur.rowcount = 0
        return cur

    class _ListCM:
        async def __aenter__(self):
            m = MagicMock()
            m.execute = execute
            return m

        async def __aexit__(self, *exc: object) -> bool:
            return False

    svc.db.org = MagicMock(return_value=_ListCM())
    authz = _tracking_authorizer(Permissions.MEMORY_READ)
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db, authorizer=authz,
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    items = asyncio_run(svc.list_connectors(ctx))
    assert len(items) == 1
    assert items[0]["kind"] == "slack"
    assert authz.required == [Permissions.MEMORY_READ]


def test_list_connectors_denies_without_memory_read() -> None:
    from teamshared.identity.rbac import PermissionDenied, Permissions

    svc, _ = _make_service({})
    authz = _tracking_authorizer()  # allow nothing
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db, authorizer=authz,
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    with pytest.raises(PermissionDenied, match="memory:read"):
        asyncio_run(svc.list_connectors(ctx))
    assert authz.required == [Permissions.MEMORY_READ]


def test_send_allows_memory_create_agent() -> None:
    """Outgoing Slack/Gmail via MCP should work for the agent role."""
    from teamshared.identity.rbac import Permissions

    row_map = {
        "SELECT id, kind, name, status, config, account_id": (
            uuid.uuid4(), "slack", "slack-me", "connected", {"channel": "C123"}, None,
        ),
        "SELECT ciphertext, nonce": (b"x", b"y"),
    }
    svc, ingestion = _make_service(row_map)
    bundle = TokenBundle(access_token="xoxp-tok")
    svc.vault.decrypt_bundle = MagicMock(return_value=bundle)
    authz = _tracking_authorizer(Permissions.MEMORY_CREATE)
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db, authorizer=authz,
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    with patch(
        "teamshared.connectors.adapters.SlackConnector.post_message",
        new=AsyncMock(return_value={"ok": True, "ts": "1.0"}),
    ):
        result = asyncio_run(
            svc.send(ctx, uuid.uuid4(), body="ping", channel="C123")
        )
    assert result["sent"] is True
    assert authz.required == [Permissions.MEMORY_CREATE]
    ingestion.ingest.assert_awaited_once()


def test_refresh_if_needed_does_not_require_manage() -> None:
    """Token refresh on a read path must not demand connector:manage."""
    from teamshared.identity.rbac import Permissions

    past = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    old = TokenBundle(access_token="old", refresh_token="1//r", expires_at=past)
    new = TokenBundle(access_token="new", refresh_token="1//r", expires_at=None)
    row_map = {
        "SELECT id, kind, name, status, config, account_id": (
            uuid.uuid4(), "gmail", "gmail-me", "connected", {}, None,
        ),
        "SELECT ciphertext, nonce": (b"x", b"y"),
        "INSERT INTO connector_tokens": None,
        "UPDATE connectors SET status": None,
    }
    svc, _ = _make_service(row_map)
    svc.vault.decrypt_bundle = MagicMock(return_value=old)
    # No permissions granted — refresh must not call require at all.
    authz = _tracking_authorizer()
    ctx = SimpleNamespace(
        principal=_principal(), db=svc.db, authorizer=authz,
        org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        request_id="req",
    )
    with patch(
        "teamshared.connectors.oauth.refresh_access_token",
        new=AsyncMock(return_value=new),
    ):
        out = asyncio_run(svc.refresh_if_needed(ctx, uuid.uuid4()))
    assert out is new
    assert Permissions.CONNECTOR_MANAGE not in authz.required
    assert authz.required == []
