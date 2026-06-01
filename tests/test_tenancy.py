"""Tenancy context helpers + RLS isolation (integration)."""

from __future__ import annotations

import uuid

import pytest

from teamshared.config import get_settings
from teamshared.tenancy.context import (
    TenantDb,
    current_org_id,
    require_org_id,
)
from teamshared.tenancy.repository import TenancyRepository


def test_current_org_id_unset() -> None:
    assert current_org_id() is None


def test_require_org_id_raises_without_context() -> None:
    with pytest.raises(RuntimeError, match="No org context"):
        require_org_id()


@pytest.mark.integration
async def test_rls_blocks_without_org_context() -> None:
    """A bare query (no org GUC) must return zero rows -- fails closed."""
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    try:
        async with db.admin() as conn:
            cur = await conn.execute("SELECT count(*) FROM memory_items")
            row = await cur.fetchone()
            assert row is not None
            assert int(row[0]) == 0
    finally:
        await db.close()


@pytest.mark.integration
async def test_rls_isolates_two_orgs() -> None:
    """Org A cannot see org B's memory even with a forced unscoped query."""
    settings = get_settings()
    db = TenantDb(settings.pg_app_dsn)
    await db.connect()
    repo = TenancyRepository(db)
    try:
        org_a = await repo.create_organization(f"a-{uuid.uuid4().hex[:8]}", "Org A")
        org_b = await repo.create_organization(f"b-{uuid.uuid4().hex[:8]}", "Org B")

        async with db.org(org_a.id) as conn:
            await conn.execute(
                "INSERT INTO memory_items (org_id, content) VALUES (%s, %s)",
                (str(org_a.id), "secret of A"),
            )
        async with db.org(org_b.id) as conn:
            await conn.execute(
                "INSERT INTO memory_items (org_id, content) VALUES (%s, %s)",
                (str(org_b.id), "secret of B"),
            )

        # Even an unscoped SELECT only returns the current tenant's row.
        async with db.org(org_a.id) as conn:
            cur = await conn.execute("SELECT content FROM memory_items")
            rows = await cur.fetchall()
            contents = {r[0] for r in rows}
            assert "secret of A" in contents
            assert "secret of B" not in contents
    finally:
        await db.close()
