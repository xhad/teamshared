"""Unit tests for AccountStore (global email identity).

Drives the store with a fake admin() connection so we pin the SECURITY DEFINER
SQL it issues and the email normalization, without a live Postgres.
"""

from __future__ import annotations

import asyncio
import uuid

from teamshared.identity.accounts import AccountStore


class _Cur:
    def __init__(self, *, one: object = None, all_: list | None = None) -> None:
        self._one = one
        self._all = all_ or []

    async def fetchone(self) -> object:
        return self._one

    async def fetchall(self) -> list:
        return self._all


class _Conn:
    def __init__(self, cur: _Cur) -> None:
        self._cur = cur
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql: str, params: object = None) -> _Cur:
        self.calls.append((sql, params))
        return self._cur


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

    def admin(self) -> _CM:
        return _CM(self._conn)


def test_upsert_calls_provision_account_with_lowercased_email() -> None:
    account_id = uuid.uuid4()
    conn = _Conn(_Cur(one=(account_id,)))
    store = AccountStore(_DB(conn))  # type: ignore[arg-type]
    out = asyncio.run(store.upsert("  Owner@Example.COM ", "Owner"))
    assert out == account_id
    sql, params = conn.calls[0]
    assert "provision_account" in sql
    assert params == ("owner@example.com", "Owner")


def test_list_orgs_maps_rows_and_normalizes_email() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    conn = _Conn(_Cur(all_=[(org_id, user_id, "acme", "Acme", "org_owner")]))
    store = AccountStore(_DB(conn))  # type: ignore[arg-type]
    out = asyncio.run(store.list_orgs("Owner@Example.com"))
    assert out == [
        {"org_id": org_id, "user_id": user_id, "slug": "acme",
         "name": "Acme", "role": "org_owner"}
    ]
    sql, params = conn.calls[0]
    assert "auth_account_orgs" in sql
    assert params == ("owner@example.com",)


def test_list_orgs_empty_for_unknown_email() -> None:
    conn = _Conn(_Cur(all_=[]))
    store = AccountStore(_DB(conn))  # type: ignore[arg-type]
    assert asyncio.run(store.list_orgs("nobody@example.com")) == []
