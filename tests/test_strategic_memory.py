"""Strategic memory pillar: store and ingestion."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from teamshared.identity.principal import Principal
from teamshared.ingestion.pipeline import IngestionPipeline, IngestionRejected
from teamshared.memory.request_context import RequestContext
from teamshared.memory.strategic import OrgStrategicStore

ORG = UUID("00000000-0000-0000-0000-000000000001")
PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")
ENTITY_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _ctx() -> RequestContext:
    principal = Principal(
        org_id=ORG,
        type="agent",
        id=PRINCIPAL_ID,
        display="cursor",
        roles=("agent",),
    )
    authorizer = MagicMock()
    authorizer.require = AsyncMock()
    return RequestContext(principal=principal, db=MagicMock(), authorizer=authorizer)


def _strategic_pipeline() -> tuple[IngestionPipeline, AsyncMock]:
    strategic = MagicMock()
    strategic.set_statement = AsyncMock(
        return_value={
            "id": ENTITY_ID,
            "org_id": ORG,
            "kind": "vision",
            "content_md": "Build the team brain",
            "version": 1,
            "status": "active",
            "created_by": "cursor",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    audit = MagicMock()
    audit.record = AsyncMock()
    pipe = IngestionPipeline(MagicMock(), audit, MagicMock(), MagicMock(), strategic, MagicMock())
    return pipe, strategic


async def test_ingest_strategic_statement_active() -> None:
    pipe, strategic = _strategic_pipeline()
    result = await pipe.ingest_strategic_statement(
        _ctx(), kind="vision", content_md="Build the team brain", agent="cursor",
    )
    assert result.status == "active"
    assert result.entity_type == "statement"
    strategic.set_statement.assert_awaited_once()
    kwargs = strategic.set_statement.await_args.kwargs
    assert kwargs["status"] == "active"


async def test_ingest_strategic_statement_rejects_secret() -> None:
    pipe, strategic = _strategic_pipeline()
    with pytest.raises(IngestionRejected, match="hard secret"):
        await pipe.ingest_strategic_statement(
            _ctx(),
            kind="mission",
            content_md="key AKIAIOSFODNN7EXAMPLE",
            agent="cursor",
        )
    strategic.set_statement.assert_not_awaited()


async def test_ingest_strategic_plan_active() -> None:
    pipe, strategic = _strategic_pipeline()
    strategic.create_plan = AsyncMock(
        return_value={
            "id": ENTITY_ID,
            "org_id": ORG,
            "name": "2026 Q2",
            "period_start": date(2026, 4, 1),
            "period_end": date(2026, 6, 30),
            "status": "active",
            "created_by": "cursor",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    result = await pipe.ingest_strategic_plan(
        _ctx(),
        name="2026 Q2",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        agent="cursor",
    )
    assert result.status == "active"
    assert result.entity_type == "plan"


async def test_activate_statement_supersedes_prior() -> None:
    """Integration-style test with mocked DB connection."""
    db = MagicMock()
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)

    store = OrgStrategicStore(db)
    await store.activate(ORG, "statement", ENTITY_ID)

    assert conn.execute.await_count == 3
    sql_calls = [str(c.args[0]) for c in conn.execute.await_args_list]
    assert any("superseded" in s for s in sql_calls)
    assert any("status = 'active'" in s for s in sql_calls)


async def test_preview_entity_statement() -> None:
    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone = AsyncMock(return_value=("vision", "We win", 2))
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)

    store = OrgStrategicStore(db)
    text = await store.preview_entity(ORG, "statement", ENTITY_ID)
    assert text is not None
    assert "vision" in text
    assert "We win" in text


async def test_search_maps_to_memory_records() -> None:
    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall = AsyncMock(return_value=[
        ("id1", "statement", "vision", "Build X", "2026-01-01T00:00:00+00:00", 0.5),
    ])
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)

    store = OrgStrategicStore(db)
    records = await store.search(ORG, "vision build", limit=5)
    assert len(records) == 1
    assert records[0].pillar == "strategic"
    assert "vision" in records[0].content.lower()
