"""WikiStore: versioned curated pages over a fake RLS-scoped connection."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from teamshared.memory.wiki import WikiStore, slugify

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 5, 28, 10, 0, tzinfo=UTC)


class _Cur:
    def __init__(self, *, one: object = None, many: list | None = None) -> None:
        self._one = one
        self._many = many or []

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
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def org(self, org_id: uuid.UUID) -> _CM:
        return _CM(self._conn)


def _page_row(version: int) -> tuple:
    return (uuid.uuid4(), "teamshared-infra", version, "Infra",
            "# Infra\n\nProd on Spark.", [uuid.uuid4()], "curator", NOW)


def test_slugify() -> None:
    assert slugify("teamshared Infra!") == "teamshared-infra"
    assert slugify("") == "untitled"


def test_upsert_increments_version_and_returns_row() -> None:
    conn = _Conn([_Cur(one=(2,)), _Cur(one=_page_row(2))])
    store = WikiStore(_DB(conn))  # type: ignore[arg-type]
    page = asyncio.run(
        store.upsert_page(
            ORG, slug="teamshared-infra", title="Infra",
            body_md="# Infra\n\nProd on Spark.", sources=[uuid.uuid4()],
        )
    )
    assert page["version"] == 2
    assert page["title"] == "Infra"
    assert isinstance(page["id"], str)
    assert all(isinstance(s, str) for s in page["sources"])
    # INSERT received the computed next version.
    insert_sql, params = conn.calls[1]
    assert "INSERT INTO wiki_pages" in insert_sql
    assert params[2] == 2  # version


def test_get_page_latest() -> None:
    conn = _Conn([_Cur(one=_page_row(5))])
    store = WikiStore(_DB(conn))  # type: ignore[arg-type]
    page = asyncio.run(store.get_page(ORG, "teamshared-infra"))
    assert page is not None
    assert page["version"] == 5
    assert "ORDER BY version DESC" in conn.calls[0][0]


def test_get_page_missing_returns_none() -> None:
    conn = _Conn([_Cur(one=None)])
    store = WikiStore(_DB(conn))  # type: ignore[arg-type]
    assert asyncio.run(store.get_page(ORG, "nope")) is None


def test_list_pages_and_versions() -> None:
    conn = _Conn([_Cur(many=[_page_row(2), _page_row(1)])])
    store = WikiStore(_DB(conn))  # type: ignore[arg-type]
    pages = asyncio.run(store.list_pages(ORG))
    assert len(pages) == 2

    conn2 = _Conn([_Cur(many=[_page_row(3), _page_row(2), _page_row(1)])])
    store2 = WikiStore(_DB(conn2))  # type: ignore[arg-type]
    versions = asyncio.run(store2.list_versions(ORG, "teamshared-infra"))
    assert [v["version"] for v in versions] == [3, 2, 1]
