"""SharedFileStore: versioned shared files over a fake RLS-scoped connection.

Mirrors tests/test_wiki_store.py. The fake DB exposes both ``org()`` (RLS-scoped,
for private CRUD) and ``admin()`` (RLS-less, for the public SECURITY DEFINER
read path).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from teamshared.memory.shared_files import SharedFileStore

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


_FILE_FIELDS = (
    "id", "org_id", "title", "content_format", "visibility", "share_token",
    "current_version", "status", "created_by", "created_at", "updated_at",
)


def _file_row(
    *, version: int = 1, visibility: str = "private",
    share_token: uuid.UUID | None = None, title: str = "Q3 file",
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


def test_create_inserts_file_and_first_version() -> None:
    file_id = uuid.uuid4()
    conn = _Conn([
        _Cur(one=(file_id, ORG, "Q3 file", "markdown", "private", None,
                  1, "active", "agent", NOW, NOW)),  # INSERT shared_files RETURNING
        _Cur(one=(file_id, 1, "# v1", "markdown", "agent", NOW)),  # INSERT version
    ])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    file = asyncio.run(
        store.create(ORG, title="Q3 file", content="# v1", content_format="markdown")
    )
    assert file["id"] == str(file_id)
    assert file["version"] == 1
    assert file["content"] == "# v1"
    # First call is the shared_files INSERT; second is the version INSERT.
    assert "INSERT INTO shared_files" in conn.calls[0][0]
    assert "INSERT INTO shared_file_versions" in conn.calls[1][0]


def test_update_appends_new_version_and_bumps_current() -> None:
    file_id = uuid.uuid4()
    conn = _Conn([
        _Cur(one=(1, "markdown")),  # SELECT current_version, content_format
        _Cur(one=(file_id, 2, "# v2", "markdown", "agent", NOW)),  # INSERT version
        _Cur(rowcount=1),  # UPDATE shared_files
        _Cur(one=(file_id, ORG, "Q3 file", "markdown", "private", None,
                  2, "active", "agent", NOW, NOW)),  # SELECT file RETURNING
    ])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    file = asyncio.run(
        store.update(ORG, file_id, content="# v2", content_format="markdown")
    )
    assert file["version"] == 2
    assert file["content"] == "# v2"
    # The version INSERT received next_version = 2.
    insert_sql, params = conn.calls[1]
    assert "INSERT INTO shared_file_versions" in insert_sql
    assert params[2] == 2  # version position


def test_update_missing_file_returns_empty() -> None:
    conn = _Conn([_Cur(one=None)])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    file = asyncio.run(
        store.update(ORG, uuid.uuid4(), content="# x")
    )
    assert file == {}


def test_publish_stamps_share_token_when_none() -> None:
    file_id = uuid.uuid4()
    token = uuid.uuid4()
    slug = "q3-file"
    conn = _Conn([
        _Cur(one=(None, None, "Q3 file")),   # SELECT share_token, slug, title (none yet)
        _Cur(one=None),                       # uniqueness check (no collision)
        _Cur(rowcount=1),                     # UPDATE with gen_random_uuid() + slug
        _Cur(one=(file_id, ORG, "Q3 file", "markdown", "published", token,
                  1, "active", "agent", NOW, NOW, slug)),  # SELECT file (12 cols)
    ])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    file = asyncio.run(store.publish(ORG, file_id))
    assert file["visibility"] == "published"
    assert file["share_token"] == str(token)
    assert file["slug"] == slug
    # The UPDATE used gen_random_uuid() and set the slug.
    update_sql = conn.calls[2][0]
    assert "gen_random_uuid()" in update_sql
    assert "slug = %s" in update_sql


def test_publish_is_idempotent_keeps_existing_token() -> None:
    file_id = uuid.uuid4()
    token = uuid.uuid4()
    slug = "q3-file"
    conn = _Conn([
        _Cur(one=(token, slug, "Q3 file")),  # SELECT share_token, slug, title (both set)
        _Cur(rowcount=1),                    # UPDATE (no gen_random_uuid, no slug)
        _Cur(one=(file_id, ORG, "Q3 file", "markdown", "published", token,
                  1, "active", "agent", NOW, NOW, slug)),  # SELECT file (12 cols)
    ])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    file = asyncio.run(store.publish(ORG, file_id))
    assert file["share_token"] == str(token)
    assert file["slug"] == slug
    # The UPDATE should NOT call gen_random_uuid() when token already exists.
    update_sql = conn.calls[1][0]
    assert "gen_random_uuid()" not in update_sql


def test_get_published_by_token_uses_admin_connection() -> None:
    token = uuid.uuid4()
    admin_conn = _Conn([
        _Cur(one=(uuid.uuid4(), ORG, "Q3 file", "markdown", 1,
                  1, "# v1", "markdown", "agent", NOW, NOW, NOW)),
    ])
    org_conn = _Conn([])
    store = SharedFileStore(_DB(org_conn, admin_conn=admin_conn))  # type: ignore[arg-type]
    file = asyncio.run(store.get_published_by_token(token))
    assert file is not None
    assert file["title"] == "Q3 file"
    assert file["content"] == "# v1"
    # The public read goes through the SECURITY DEFINER function over admin().
    assert "public_shared_file_by_token" in admin_conn.calls[0][0]


def test_get_published_by_token_missing_returns_none() -> None:
    admin_conn = _Conn([_Cur(one=None)])
    store = SharedFileStore(_DB(_Conn([]), admin_conn=admin_conn))  # type: ignore[arg-type]
    assert asyncio.run(store.get_published_by_token(uuid.uuid4())) is None


def test_list_published_versions() -> None:
    token = uuid.uuid4()
    admin_conn = _Conn([
        _Cur(many=[(3, "agent", NOW), (2, "agent", NOW), (1, "agent", NOW)]),
    ])
    store = SharedFileStore(_DB(_Conn([]), admin_conn=admin_conn))  # type: ignore[arg-type]
    versions = asyncio.run(store.list_published_versions(token))
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert "public_shared_file_versions_list" in admin_conn.calls[0][0]


def test_archive_marks_archived() -> None:
    conn = _Conn([_Cur(rowcount=1)])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    changed = asyncio.run(store.archive(ORG, uuid.uuid4()))
    assert changed is True
    assert "status = 'archived'" in conn.calls[0][0]


def test_list_plans_with_query_filters_by_title_ilike() -> None:
    file_id = uuid.uuid4()
    token = uuid.uuid4()
    conn = _Conn([
        _Cur(many=[(file_id, ORG, "Yield Vault Modeller", "html", "published", token,
                    1, "active", "agent", NOW, NOW, "yield-vault-modeller")]),
    ])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    rows = asyncio.run(store.list_plans(ORG, query="yield vault"))
    assert len(rows) == 1
    assert rows[0]["slug"] == "yield-vault-modeller"
    sql, params = conn.calls[0]
    assert "ILIKE" in sql
    assert params[0] == "%yield vault%"


def test_archive_missing_returns_false() -> None:
    conn = _Conn([_Cur(rowcount=0)])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    changed = asyncio.run(store.archive(ORG, uuid.uuid4()))
    assert changed is False


def test_unpublish_flips_visibility_back_to_private() -> None:
    file_id = uuid.uuid4()
    token = uuid.uuid4()
    conn = _Conn([
        _Cur(rowcount=1),  # UPDATE
        _Cur(one=(file_id, ORG, "Q3 file", "markdown", "private", token,
                  1, "active", "agent", NOW, NOW)),  # SELECT file
    ])
    store = SharedFileStore(_DB(conn))  # type: ignore[arg-type]
    file = asyncio.run(store.unpublish(ORG, file_id))
    assert file["visibility"] == "private"
    # Token is retained for audit.
    assert file["share_token"] == str(token)
