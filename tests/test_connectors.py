"""Connector vault (unit) + framework wiring (integration)."""

from __future__ import annotations

import base64
import os
import uuid

import pytest

from teamshared.connectors.base import Connector, SourceDoc, SyncResult
from teamshared.connectors.registry import CONNECTOR_KINDS, build_connector
from teamshared.connectors.vault import TokenVault


def test_vault_roundtrip() -> None:
    key = base64.b64encode(os.urandom(32)).decode()
    vault = TokenVault(key)
    ct, nonce, key_id = vault.encrypt("xoxb-super-secret")
    assert ct != b"xoxb-super-secret"
    assert vault.decrypt(ct, nonce) == "xoxb-super-secret"
    assert len(key_id) == 12


def test_vault_dev_key_roundtrip() -> None:
    vault = TokenVault(None)
    ct, nonce, _ = vault.encrypt("token")
    assert vault.decrypt(ct, nonce) == "token"


def test_registry_knows_all_kinds() -> None:
    for kind in ("slack", "github", "notion", "gdrive", "linear", "mcp"):
        assert kind in CONNECTOR_KINDS
    assert build_connector("github", {"repo": "a/b"}).kind == "github"


def test_registry_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown connector kind"):
        build_connector("dropbox", {})


class _FakeConnector(Connector):
    kind = "fake"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        return SyncResult(
            documents=[
                SourceDoc(external_id="1", content="incident retro: cache stampede fixed"),
                SourceDoc(external_id="2", content="runbook: how to rotate the signing key"),
            ],
            next_cursor="page2",
        )


@pytest.mark.integration
async def test_connector_sync_imports_active_memories() -> None:
    from teamshared.config import get_settings
    from teamshared.identity.rbac import Authorizer
    from teamshared.memory.request_context import RequestContext
    from teamshared.server.services import build_services

    settings = get_settings()
    services = await build_services(settings)
    try:
        # An owner-scoped principal who can manage connectors + approve.
        from teamshared.identity.provisioning import signup_org

        result = await signup_org(
            repo=services.tenancy, api_keys=services.api_keys, roles=services.roles,
            accounts=services.accounts,
            org_slug=f"c2-{uuid.uuid4().hex[:8]}", org_name="ConnCo2", owner_email="o@c.test",
        )
        principal = await services.api_keys.authenticate(result.api_key.token)
        assert principal is not None
        ctx = RequestContext(
            principal=principal, db=services.tenant_db, authorizer=Authorizer(services.tenant_db)
        )
        cid = await services.connectors.create(
            ctx, kind="github", name="repo", config={"repo": "a/b"}
        )
        report = await services.connectors.sync(ctx, cid, connector=_FakeConnector({}))
        assert report.fetched == 2
        assert report.imported == 2
        subjects = await services.vector_store.list_subjects(ctx.org_id, limit=10)
        assert len(subjects) >= 2
    finally:
        await services.tenant_db.close()
