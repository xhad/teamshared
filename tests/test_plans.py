"""PlanStore: versioned plans over a fake RLS-scoped connection.

Mirrors tests/test_wiki_store.py. The fake DB exposes both ``org()`` (RLS-scoped,
for private CRUD) and ``admin()`` (RLS-less, for the public SECURITY DEFINER
read path).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from teamshared.memory.plans import PlanStore

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class _Cur:
    def __init__(self, *, one: object = None, many: list | None = None, rowcount: int = 0) -> None:
        self._one = one
        self._many = many or []
        self.rowcount = rowcount

    async def fetchone(self) -> object:
        return self._one

    async def fetchall(self) -> list:
        return self._many


class _Conn:
    def __init__(self, curs: list[_Cur]) -> None:
        self._curs = list(curs)
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql: str, params: object = None) -> _Cur:
        self.calls.append((sql, params))
        return self._curs.pop(0)


class _CM:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _DB:
    """Fake TenantDb with both org() and admin() context managers."""

    def __init__(self, conn: _Conn, admin_conn: _Conn | None = None) -> None:
        self._conn = conn
        self._admin_conn = admin_conn or conn

    def org(self, org_id: uuid.UUID) -> _CM:
        return _CM(self._conn)

    def admin(self) -> _CM:
        return _CM(self._admin_conn)


_PLAN_FIELDS = (
    "id", "org_id", "title", "content_format", "visibility", "share_token",
    "current_version", "status", "created_by", "created_at", "updated_at",
)


def _plan_row(
    *, version: int = 1, visibility: str = "private",
    share_token: uuid.UUID | None = None, title: str = "Q3 plan",
    fmt: str = "markdown",
) -> tuple:
    return (
        uuid.uuid4(), ORG, title, fmt, visibility, share_token,
        version, "active", "agent", NOW, NOW,
    )


def _version_row(*, version: int = 1, fmt: str = "markdown") -> tuple:
    return (
        uuid.uuid4(), version, f"# v{version}", fmt, "agent", NOW,
    )


def test_create_inserts_plan_and_first_version() -> None:
    plan_id = uuid.uuid4()
    conn = _Conn([
        _Cur(one=(plan_id, ORG, "Q3 plan", "markdown", "private", None,
                  1, "active", "agent", NOW, NOW)),  # INSERT plans RETURNING
        _Cur(one=(plan_id, 1, "# v1", "markdown", "agent", NOW)),  # INSERT version
    ])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    plan = asyncio.run(
        store.create(ORG, title="Q3 plan", content="# v1", content_format="markdown")
    )
    assert plan["id"] == str(plan_id)
    assert plan["version"] == 1
    assert plan["content"] == "# v1"
    # First call is the plans INSERT; second is the version INSERT.
    assert "INSERT INTO plans" in conn.calls[0][0]
    assert "INSERT INTO plan_versions" in conn.calls[1][0]


def test_update_appends_new_version_and_bumps_current() -> None:
    plan_id = uuid.uuid4()
    conn = _Conn([
        _Cur(one=(1, "markdown")),  # SELECT current_version, content_format
        _Cur(one=(plan_id, 2, "# v2", "markdown", "agent", NOW)),  # INSERT version
        _Cur(rowcount=1),  # UPDATE plans
        _Cur(one=(plan_id, ORG, "Q3 plan", "markdown", "private", None,
                  2, "active", "agent", NOW, NOW)),  # SELECT plan RETURNING
    ])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    plan = asyncio.run(
        store.update(ORG, plan_id, content="# v2", content_format="markdown")
    )
    assert plan["version"] == 2
    assert plan["content"] == "# v2"
    # The version INSERT received next_version = 2.
    insert_sql, params = conn.calls[1]
    assert "INSERT INTO plan_versions" in insert_sql
    assert params[2] == 2  # version position


def test_update_missing_plan_returns_empty() -> None:
    conn = _Conn([_Cur(one=None)])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    plan = asyncio.run(
        store.update(ORG, uuid.uuid4(), content="# x")
    )
    assert plan == {}


def test_publish_stamps_share_token_when_none() -> None:
    plan_id = uuid.uuid4()
    token = uuid.uuid4()
    conn = _Conn([
        _Cur(one=(None,)),  # SELECT share_token (none yet)
        _Cur(rowcount=1),  # UPDATE with gen_random_uuid()
        _Cur(one=(plan_id, ORG, "Q3 plan", "markdown", "published", token,
                  1, "active", "agent", NOW, NOW)),  # SELECT plan
    ])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    plan = asyncio.run(store.publish(ORG, plan_id))
    assert plan["visibility"] == "published"
    assert plan["share_token"] == str(token)
    # The UPDATE used gen_random_uuid().
    update_sql = conn.calls[1][0]
    assert "gen_random_uuid()" in update_sql


def test_publish_is_idempotent_keeps_existing_token() -> None:
    plan_id = uuid.uuid4()
    token = uuid.uuid4()
    conn = _Conn([
        _Cur(one=(token,)),  # SELECT share_token (already set)
        _Cur(rowcount=1),  # UPDATE (no gen_random_uuid)
        _Cur(one=(plan_id, ORG, "Q3 plan", "markdown", "published", token,
                  1, "active", "agent", NOW, NOW)),
    ])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    plan = asyncio.run(store.publish(ORG, plan_id))
    assert plan["share_token"] == str(token)
    # The UPDATE should NOT call gen_random_uuid() when token already exists.
    update_sql = conn.calls[1][0]
    assert "gen_random_uuid()" not in update_sql


def test_get_published_by_token_uses_admin_connection() -> None:
    token = uuid.uuid4()
    admin_conn = _Conn([
        _Cur(one=(uuid.uuid4(), ORG, "Q3 plan", "markdown", 1,
                  1, "# v1", "markdown", "agent", NOW, NOW, NOW)),
    ])
    org_conn = _Conn([])
    store = PlanStore(_DB(org_conn, admin_conn=admin_conn))  # type: ignore[arg-type]
    plan = asyncio.run(store.get_published_by_token(token))
    assert plan is not None
    assert plan["title"] == "Q3 plan"
    assert plan["content"] == "# v1"
    # The public read goes through the SECURITY DEFINER function over admin().
    assert "public_plan_by_token" in admin_conn.calls[0][0]


def test_get_published_by_token_missing_returns_none() -> None:
    admin_conn = _Conn([_Cur(one=None)])
    store = PlanStore(_DB(_Conn([]), admin_conn=admin_conn))  # type: ignore[arg-type]
    assert asyncio.run(store.get_published_by_token(uuid.uuid4())) is None


def test_list_published_versions() -> None:
    token = uuid.uuid4()
    admin_conn = _Conn([
        _Cur(many=[(3, "agent", NOW), (2, "agent", NOW), (1, "agent", NOW)]),
    ])
    store = PlanStore(_DB(_Conn([]), admin_conn=admin_conn))  # type: ignore[arg-type]
    versions = asyncio.run(store.list_published_versions(token))
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert "public_plan_versions_list" in admin_conn.calls[0][0]


def test_archive_marks_archived() -> None:
    conn = _Conn([_Cur(rowcount=1)])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    changed = asyncio.run(store.archive(ORG, uuid.uuid4()))
    assert changed is True
    assert "status = 'archived'" in conn.calls[0][0]


def test_archive_missing_returns_false() -> None:
    conn = _Conn([_Cur(rowcount=0)])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    changed = asyncio.run(store.archive(ORG, uuid.uuid4()))
    assert changed is False


def test_unpublish_flips_visibility_back_to_private() -> None:
    plan_id = uuid.uuid4()
    token = uuid.uuid4()
    conn = _Conn([
        _Cur(rowcount=1),  # UPDATE
        _Cur(one=(plan_id, ORG, "Q3 plan", "markdown", "private", token,
                  1, "active", "agent", NOW, NOW)),  # SELECT plan
    ])
    store = PlanStore(_DB(conn))  # type: ignore[arg-type]
    plan = asyncio.run(store.unpublish(ORG, plan_id))
    assert plan["visibility"] == "private"
    # Token is retained for audit.
    assert plan["share_token"] == str(token)
