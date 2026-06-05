"""Unit tests for the AdminService write gaps added in Phase 5.

Drive the methods with fake db/roles/audit/authorizer so we pin the RBAC check,
the SQL issued, and the audit trail without a live Postgres.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from teamshared.admin.service import AdminService
from teamshared.identity.roles import RoleStore

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
AGENT = uuid.UUID("44444444-4444-4444-4444-444444444444")


class _Cur:
    def __init__(self, *, one: object = None, rowcount: int = 1) -> None:
        self._one = one
        self.rowcount = rowcount

    async def fetchone(self) -> object:
        return self._one

    async def fetchall(self) -> list:
        return []


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

    def admin(self) -> _CM:
        return _CM(self._conn)


class _Ctx:
    def __init__(self) -> None:
        self.org_id = ORG
        self.request_id = "req1"
        self.authorizer = type("A", (), {"require": AsyncMock()})()
        self.principal = type(
            "P", (), {"attribution": "owner", "type": "user", "id": ACTOR}
        )()


def _admin(conn: _Conn, roles: object | None = None) -> AdminService:
    audit = type("Audit", (), {"record": AsyncMock()})()
    roles = roles or RoleStore(_DB(conn))  # type: ignore[arg-type]
    return AdminService(_DB(conn), roles, audit)  # type: ignore[arg-type]


def test_set_agent_status_requires_admin_updates_and_audits() -> None:
    conn = _Conn([_Cur(rowcount=1)])
    admin = _admin(conn)
    ctx = _Ctx()
    ok = asyncio.run(admin.set_agent_status(ctx, AGENT, "disabled"))  # type: ignore[arg-type]
    assert ok is True
    ctx.authorizer.require.assert_awaited_once()
    sql, params = conn.calls[0]
    assert "UPDATE agents SET status" in sql
    assert params == ("disabled", str(AGENT))
    admin.audit.record.assert_awaited_once()


def test_set_agent_status_rejects_bad_status() -> None:
    conn = _Conn([])
    admin = _admin(conn)
    with pytest.raises(ValueError, match="invalid agent status"):
        asyncio.run(admin.set_agent_status(_Ctx(), AGENT, "bogus"))  # type: ignore[arg-type]


def test_grant_role_to_user_syncs_membership_and_replaces_binding() -> None:
    # User path: replace the RBAC binding (set_user_role) AND update the
    # memberships row so the People list reflects the new role.
    user_id = uuid.uuid4()
    roles = type("R", (), {"set_user_role": AsyncMock()})()
    conn = _Conn([_Cur(rowcount=1)])  # the memberships UPDATE
    admin = _admin(conn, roles=roles)
    ctx = _Ctx()
    ok = asyncio.run(
        admin.grant_role(  # type: ignore[arg-type]
            ctx, principal_type="user", principal_id=user_id, role_name="org_admin"
        )
    )
    assert ok is True
    roles.set_user_role.assert_awaited_once_with(
        org_id=ORG, principal_id=user_id, role_name="org_admin"
    )
    sql, params = conn.calls[0]
    assert "UPDATE memberships SET role" in sql
    assert params == ("org_admin", str(ORG), str(user_id))
    admin.audit.record.assert_awaited_once()


def test_grant_role_to_agent_uses_binding_only() -> None:
    # Agent path: bind a role, never touch memberships.
    roles = type("R", (), {"bind_role": AsyncMock(return_value=True)})()
    conn = _Conn([])
    admin = _admin(conn, roles=roles)
    ctx = _Ctx()
    ok = asyncio.run(
        admin.grant_role(  # type: ignore[arg-type]
            ctx, principal_type="agent", principal_id=AGENT, role_name="agent"
        )
    )
    assert ok is True
    roles.bind_role.assert_awaited_once()
    assert conn.calls == []  # no membership update for agents
    admin.audit.record.assert_awaited_once()


def test_rolestore_bind_dedupes_null_scope() -> None:
    # Org-wide bindings (NULL scope) must dedupe via NOT EXISTS, since the
    # table's UNIQUE constraint treats NULL scope columns as distinct.
    role_id = uuid.uuid4()
    conn = _Conn([_Cur(one=(role_id,)), _Cur(rowcount=0)])
    store = RoleStore(_DB(conn))  # type: ignore[arg-type]
    ok = asyncio.run(
        store.bind_role(
            org_id=ORG, principal_type="agent", principal_id=AGENT, role_name="agent"
        )
    )
    assert ok is False  # already bound -> NOT EXISTS short-circuits the insert
    insert_sql = conn.calls[1][0]
    assert "WHERE NOT EXISTS" in insert_sql
    assert "IS NOT DISTINCT FROM" in insert_sql


def test_rolestore_set_user_role_replaces_then_inserts() -> None:
    role_id = uuid.uuid4()
    user_id = uuid.uuid4()
    # resolve_role_id, DELETE existing system bindings, INSERT the new one.
    conn = _Conn([_Cur(one=(role_id,)), _Cur(rowcount=2), _Cur(rowcount=1)])
    store = RoleStore(_DB(conn))  # type: ignore[arg-type]
    asyncio.run(
        store.set_user_role(org_id=ORG, principal_id=user_id, role_name="member")
    )
    assert "DELETE FROM role_bindings" in conn.calls[1][0]
    assert "INSERT INTO role_bindings" in conn.calls[2][0]


def test_revoke_role_delegates_and_audits() -> None:
    roles = type("R", (), {"unbind_role": AsyncMock(return_value=True)})()
    admin = _admin(_Conn([]), roles=roles)
    ctx = _Ctx()
    ok = asyncio.run(
        admin.revoke_role(ctx, principal_type="agent", principal_id=AGENT, role_name="member")  # type: ignore[arg-type]
    )
    assert ok is True
    roles.unbind_role.assert_awaited_once()
    admin.audit.record.assert_awaited_once()


def test_add_member_provisions_account_user_membership_and_role() -> None:
    account_id = uuid.uuid4()
    new_user = uuid.uuid4()
    # Cursors consumed in order: provision_account (admin), users upsert (org),
    # memberships upsert (org).
    conn = _Conn([_Cur(one=(account_id,)), _Cur(one=(new_user,)), _Cur(rowcount=1)])
    roles = type("R", (), {"bind_role": AsyncMock(return_value=True)})()
    admin = _admin(conn, roles=roles)
    ctx = _Ctx()
    out = asyncio.run(
        admin.add_member(ctx, email="New.Person@Team.io", role="member")  # type: ignore[arg-type]
    )
    ctx.authorizer.require.assert_awaited_once()
    # Email is lowercased before any store call.
    assert out == {"user_id": str(new_user), "email": "new.person@team.io", "role": "member"}
    assert "provision_account" in conn.calls[0][0]
    assert conn.calls[0][1] == ("new.person@team.io", None)
    assert "INSERT INTO users" in conn.calls[1][0]
    assert "INSERT INTO memberships" in conn.calls[2][0]
    roles.bind_role.assert_awaited_once()
    admin.audit.record.assert_awaited_once()


def test_add_member_rejects_blank_email() -> None:
    admin = _admin(_Conn([]))
    with pytest.raises(ValueError, match="email is required"):
        asyncio.run(admin.add_member(_Ctx(), email="   ", role="member"))  # type: ignore[arg-type]


def test_rolestore_unbind_resolves_then_deletes() -> None:
    role_id = uuid.uuid4()
    conn = _Conn([_Cur(one=(role_id,)), _Cur(rowcount=1)])
    store = RoleStore(_DB(conn))  # type: ignore[arg-type]
    ok = asyncio.run(
        store.unbind_role(org_id=ORG, principal_type="agent", principal_id=AGENT, role_name="member")
    )
    assert ok is True
    assert "DELETE FROM role_bindings" in conn.calls[1][0]


def test_rolestore_unbind_unknown_role_returns_false() -> None:
    conn = _Conn([_Cur(one=None)])
    store = RoleStore(_DB(conn))  # type: ignore[arg-type]
    ok = asyncio.run(
        store.unbind_role(org_id=ORG, principal_type="agent", principal_id=AGENT, role_name="nope")
    )
    assert ok is False
