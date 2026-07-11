from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from teamshared.admin.retention import enforce_retention


def _db(*, apply_rowcount: int = 0):
    policy_id = uuid.uuid4()
    policy_cursor = MagicMock()
    policy_cursor.fetchall = AsyncMock(
        return_value=[(policy_id, "90-day facts", 90, 100, ["fact"])]
    )
    result_cursor = MagicMock()
    result_cursor.fetchone = AsyncMock(return_value=(3,))
    result_cursor.rowcount = apply_rowcount
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=[policy_cursor, result_cursor])

    @asynccontextmanager
    async def org(_: uuid.UUID):
        yield conn

    return SimpleNamespace(org=org), conn


async def test_retention_dry_run_counts_without_mutating() -> None:
    db, conn = _db()
    report = await enforce_retention(db, uuid.uuid4(), dry_run=True)

    assert report["would_soft_delete"] == 3
    assert report["soft_deleted"] == 0
    sql = conn.execute.await_args_list[1].args[0]
    assert "SELECT count(*) FROM candidates" in sql
    assert "kind = ANY" in sql


async def test_retention_apply_soft_deletes_candidates() -> None:
    db, conn = _db(apply_rowcount=2)
    report = await enforce_retention(db, uuid.uuid4(), dry_run=False)

    assert report["soft_deleted"] == 2
    sql = conn.execute.await_args_list[1].args[0]
    assert "UPDATE memory_items" in sql
    assert "status = 'soft_deleted'" in sql
