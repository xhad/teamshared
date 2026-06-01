"""VectorStore: embedder + scope-filter unit tests, store integration tests."""

from __future__ import annotations

import uuid

import pytest

from teamshared.config import get_settings
from teamshared.memory.embeddings import HashEmbedder
from teamshared.memory.vectorstore import ScopeFilter, VectorStore, content_hash
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository


async def test_hash_embedder_is_deterministic_and_sized() -> None:
    emb = HashEmbedder(1536)
    a, b = await emb.embed(["hello", "hello"])
    assert len(a) == 1536
    assert a == b
    (c,) = await emb.embed(["different"])
    assert c != a


def test_scope_filter_org_only() -> None:
    sql, params = ScopeFilter(include_org=True, include_shared=False).where("mi")
    assert "mi.scope = 'org'" in sql
    assert params == []


def test_scope_filter_user_and_team() -> None:
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    sql, params = ScopeFilter(
        user_id=uid, team_ids=[tid], include_org=False, include_shared=False
    ).where("mi")
    assert "scope = 'user'" in sql
    assert "scope = 'team'" in sql
    assert str(uid) in params
    assert [str(tid)] in params


def test_scope_filter_empty_is_false() -> None:
    sql, _params = ScopeFilter(
        include_org=False, include_shared=False
    ).where("mi")
    assert sql == "false"


def test_content_hash_normalizes() -> None:
    assert content_hash("Hello World ") == content_hash("hello world")


@pytest.mark.integration
async def test_vectorstore_add_and_search_is_tenant_scoped() -> None:
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    store = VectorStore(db, HashEmbedder(settings.embed_dims))
    try:
        org_a = await repo.create_organization(f"a-{uuid.uuid4().hex[:8]}", "A")
        org_b = await repo.create_organization(f"b-{uuid.uuid4().hex[:8]}", "B")
        await store.add(org_id=org_a.id, content="alpha deployment runbook", scope="org")
        await store.add(org_id=org_b.id, content="beta deployment runbook", scope="org")

        sf = ScopeFilter(include_org=True, include_shared=True)
        hits_a = await store.search(org_id=org_a.id, query="deployment runbook", scope_filter=sf, k=5)
        contents = {h.content for h in hits_a}
        assert "alpha deployment runbook" in contents
        assert "beta deployment runbook" not in contents
        for h in hits_a:
            assert h.org_id == org_a.id
    finally:
        await db.close()
