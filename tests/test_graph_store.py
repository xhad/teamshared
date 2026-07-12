"""Graph store unit tests: neighbor dedup on multi-path/bidirectional edges."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from teamshared.memory.graph_pg import PostgresGraphStore

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def test_pg_related_dedupes_bidirectional_edges() -> None:
    """An entity related in both directions must appear once, not per edge row."""
    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall = AsyncMock(
        return_value=[
            ("mex-memory", "related_to", 1),
            ("mex-memory", "related_to", 1),
            ("teamshared", "works_on", 1),
        ]
    )
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)

    store = PostgresGraphStore(db)
    records = await store.related("mex", org_id=str(ORG), depth=2, limit=20)
    names = [r.subject for r in records]
    assert names == ["mex-memory", "teamshared"]
