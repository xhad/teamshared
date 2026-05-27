"""Procedural-store integration tests.

Run against the dev compose stack::

    docker compose -f infra/docker-compose.yml up -d postgres
    actx migrate
    pytest -m integration tests/test_procedural_integration.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from actx.memory.procedural import ProceduralStore

pytestmark = pytest.mark.integration


def _dsn() -> str:
    user = os.environ.get("ACTX_PG_USER", "actx")
    password = os.environ.get("ACTX_PG_PASSWORD", "actx")
    host = os.environ.get("ACTX_PG_HOST", "localhost")
    port = os.environ.get("ACTX_PG_PORT", "5432")
    db = os.environ.get("ACTX_PG_DB", "actx")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest_asyncio.fixture
async def store() -> AsyncIterator[ProceduralStore]:
    s = ProceduralStore(_dsn())
    await s.connect()
    try:
        async with s.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("TRUNCATE procedures RESTART IDENTITY")
        yield s
    finally:
        await s.close()


async def test_set_and_get_procedure(store: ProceduralStore) -> None:
    inserted = await store.set_procedure(
        "deploy-blog",
        "1. Build static site.\n2. Sync to S3.",
        agent="cursor",
        description="Push the blog",
        tags=["deploy"],
    )
    assert inserted["version"] == 1
    fetched = await store.get_procedure("deploy-blog")
    assert fetched is not None
    assert fetched["steps_md"].startswith("1. Build")


async def test_versions_increment(store: ProceduralStore) -> None:
    await store.set_procedure("p", "v1 steps", agent="cursor")
    v2 = await store.set_procedure("p", "v2 steps", agent="cursor")
    assert v2["version"] == 2
    latest = await store.get_procedure("p")
    assert latest is not None
    assert latest["version"] == 2
    older = await store.get_procedure("p", version=1)
    assert older is not None
    assert older["steps_md"] == "v1 steps"


async def test_list_returns_latest_per_name(store: ProceduralStore) -> None:
    await store.set_procedure("p1", "v1", agent="cursor")
    await store.set_procedure("p1", "v2", agent="cursor")
    await store.set_procedure("p2", "v1", agent="hermes", tags=["x"])
    listed = await store.list_procedures()
    names = {row["name"]: row["version"] for row in listed}
    assert names["p1"] == 2
    assert names["p2"] == 1
    tagged = await store.list_procedures(tag="x")
    assert len(tagged) == 1
    assert tagged[0]["name"] == "p2"


async def test_search_procedures(store: ProceduralStore) -> None:
    await store.set_procedure(
        "deploy-blog", "Sync static site to S3", agent="cursor", description="deploy blog"
    )
    await store.set_procedure(
        "rotate-keys", "Rotate the AWS access keys", agent="cursor"
    )
    hits = await store.search_procedures("deploy", limit=5)
    assert any(r.metadata["name"] == "deploy-blog" for r in hits)
