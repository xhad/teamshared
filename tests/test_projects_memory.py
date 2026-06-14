"""Projects pillar + work hierarchy: store-level SQL behaviour (mocked DB)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from teamshared.memory.projects import ProjectStore
from teamshared.memory.work import WorkStore

ORG = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
WORK_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _mock_db(*, fetchone=None, fetchall=None):
    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone = AsyncMock(return_value=fetchone)
    cur.fetchall = AsyncMock(return_value=fetchall or [])
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)
    return db, conn


async def test_list_projects_excludes_archived_by_default() -> None:
    db, conn = _mock_db(fetchall=[])
    store = ProjectStore(db)
    await store.list_projects(ORG)
    sql = conn.execute.await_args.args[0]
    assert "project_status = 'active'" in sql


async def test_list_projects_include_archived_omits_filter() -> None:
    db, conn = _mock_db(fetchall=[])
    store = ProjectStore(db)
    await store.list_projects(ORG, include_archived=True)
    sql = conn.execute.await_args.args[0]
    assert "project_status = 'active'" not in sql


async def test_add_section_defaults_sort_order_to_max_plus_one() -> None:
    db, conn = _mock_db()
    # first call returns max+1, second returns the inserted row
    conn.execute.return_value.fetchone = AsyncMock(
        side_effect=[(3.0,), (str(UUID(int=9)), str(ORG), str(PROJECT_ID), "Doing", 3.0, None)]
    )
    store = ProjectStore(db)
    row = await store.add_section(ORG, PROJECT_ID, name="Doing")
    assert row["name"] == "Doing"
    assert row["sort_order"] == 3.0


async def test_list_project_items_filters_subtasks_and_closed() -> None:
    db, conn = _mock_db(fetchall=[])
    store = WorkStore(db)
    await store.list_project_items(ORG, PROJECT_ID)
    sql = conn.execute.await_args.args[0]
    assert "JOIN work_items wi" in sql
    assert "wi.parent_id IS NULL" in sql
    assert "wi.work_status NOT IN ('done', 'cancelled')" in sql


async def test_list_subtasks_queries_parent() -> None:
    db, conn = _mock_db(fetchall=[])
    store = WorkStore(db)
    await store.list_subtasks(ORG, WORK_ID)
    sql = conn.execute.await_args.args[0]
    assert "parent_id = %s" in sql


async def test_add_dependency_returns_existing_flag_when_conflict() -> None:
    db, _conn = _mock_db(fetchone=None)  # ON CONFLICT DO NOTHING -> no row
    store = WorkStore(db)
    result = await store.add_dependency(ORG, blocker_id=WORK_ID, blocked_id=PROJECT_ID)
    assert result["already_exists"] is True


async def test_add_to_project_upserts_membership() -> None:
    db, conn = _mock_db()
    conn.execute.return_value.fetchone = AsyncMock(
        side_effect=[
            (1.0,),  # max sort_order
            (str(UUID(int=5)), str(ORG), str(WORK_ID), str(PROJECT_ID), None, 1.0, None),
        ]
    )
    store = WorkStore(db)
    row = await store.add_to_project(ORG, WORK_ID, PROJECT_ID)
    assert row["work_item_id"] == str(WORK_ID)
    assert row["project_id"] == str(PROJECT_ID)
    insert_sql = conn.execute.await_args.args[0]
    assert "ON CONFLICT (org_id, work_item_id, project_id)" in insert_sql
