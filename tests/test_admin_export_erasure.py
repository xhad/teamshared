"""Export and user-memory erasure on AdminService."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from teamshared.admin.exceptions import (
    ExportTooLargeError,
    SelfErasureBlockedError,
    UserNotInOrgError,
)
from teamshared.admin.service import AdminService
from teamshared.identity.roles import RoleStore

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
TARGET = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _Cur:
    def __init__(self, *, one: object = None, rows: list | None = None, rowcount: int = 0) -> None:
        self._one = one
        self._rows = rows or []
        self.rowcount = rowcount

    async def fetchone(self) -> object:
        return self._one

    async def fetchall(self) -> list:
        return self._rows


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


class _Ctx:
    def __init__(self, *, actor_id: uuid.UUID = ACTOR) -> None:
        self.org_id = ORG
        self.request_id = "req-export"
        self.authorizer = type("A", (), {"require": AsyncMock()})()
        self.principal = type(
            "P", (), {"attribution": "owner", "type": "user", "id": actor_id}
        )()


def _admin(conn: _Conn, *, export_max_items: int = 50_000) -> AdminService:
    audit = type("Audit", (), {"record": AsyncMock()})()
    return AdminService(
        _DB(conn), RoleStore(_DB(conn)), audit, export_max_items=export_max_items  # type: ignore[arg-type]
    )


def test_export_raises_when_over_cap() -> None:
    conn = _Conn([_Cur(one=(100_001,))])
    admin = _admin(conn, export_max_items=100_000)
    with pytest.raises(ExportTooLargeError):
        asyncio.run(admin.export_memory(_Ctx()))  # type: ignore[arg-type]


def test_export_includes_procedures_and_audits() -> None:
    item_row = (
        uuid.uuid4(), "semantic", "fact", "org", "shared", "hello", None, [],
        "manual", None, None, None, None,
    )
    proc_row = ("ship-pr", 1, "desc", "# steps", None, [], "cursor", None, "active")
    conn = _Conn([
        _Cur(one=(1,)),
        _Cur(rows=[item_row]),
        _Cur(rows=[proc_row]),
    ])
    admin = _admin(conn)
    out = asyncio.run(admin.export_memory(_Ctx()))  # type: ignore[arg-type]
    assert out["counts"]["memory_items"] == 1
    assert out["counts"]["procedures"] == 1
    assert out["schema_version"] == 1
    admin.audit.record.assert_awaited_once()


def test_purge_soft_deletes_and_requires_member() -> None:
    conn = _Conn([_Cur(one=(1,)), _Cur(rowcount=3)])
    admin = _admin(conn)
    deleted = asyncio.run(admin.purge_user_memory(_Ctx(), TARGET))  # type: ignore[arg-type]
    assert deleted == 3
    sql, params = conn.calls[1]
    assert "soft_deleted" in sql
    assert params == (str(TARGET), str(TARGET))
    admin.audit.record.assert_awaited_once()


def test_purge_rejects_unknown_member() -> None:
    conn = _Conn([_Cur(one=None)])
    admin = _admin(conn)
    with pytest.raises(UserNotInOrgError):
        asyncio.run(admin.purge_user_memory(_Ctx(), TARGET))  # type: ignore[arg-type]


def test_purge_blocks_self() -> None:
    admin = _admin(_Conn([]))
    with pytest.raises(SelfErasureBlockedError):
        asyncio.run(admin.purge_user_memory(_Ctx(actor_id=ACTOR), ACTOR))  # type: ignore[arg-type]
