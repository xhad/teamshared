"""Consent store: the human gate for agent capture.

Unit-tests the SQL-backed store against a fake `TenantDb` that records executed
statements and returns canned rows, plus the pure allow/merge/status logic.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from teamshared.ingestion.consent import (
    BASELINE_PROFILE,
    ConsentStore,
    _merge_profile,
    _status,
)

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER = uuid.UUID("33333333-3333-3333-3333-333333333333")


class _Cur:
    def __init__(self, one: tuple | None = None, all_: list[tuple] | None = None,
                 rowcount: int = 0) -> None:
        self._one = one
        self._all = all_ or []
        self.rowcount = rowcount

    async def fetchone(self) -> tuple | None:
        return self._one

    async def fetchall(self) -> list[tuple]:
        return self._all


class _Conn:
    def __init__(self, results: list[_Cur]) -> None:
        self._results = list(results)
        self.calls: list[tuple] = []

    async def execute(self, sql: str, params: object = None) -> _Cur:
        self.calls.append((sql, params))
        return self._results.pop(0) if self._results else _Cur()


class _OrgCM:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeDb:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def org(self, org_id: object) -> _OrgCM:
        return _OrgCM(self.conn)


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #
def test_merge_profile_locks_secret_redaction() -> None:
    merged = _merge_profile({"redact_secrets": False, "redact_emails": False})
    assert merged["redact_secrets"] is True  # locked rule cannot be loosened
    assert merged["redact_emails"] is False  # non-locked rule honored
    assert set(merged) == set(BASELINE_PROFILE)


def test_status_transitions() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    assert _status("review", None, None) == "active"
    assert _status("review", future, None) == "active"
    assert _status("review", past, None) == "expired"
    assert _status("off", None, None) == "off"
    assert _status("review", None, past) == "revoked"


# --------------------------------------------------------------------------- #
# Store SQL behavior
# --------------------------------------------------------------------------- #
def test_grant_filters_scope_and_persists_locked_profile() -> None:
    conn = _Conn([_Cur(one=(uuid.uuid4(),))])
    store = ConsentStore(_FakeDb(conn))  # type: ignore[arg-type]
    asyncio.run(
        store.grant(
            ORG,
            agent="cursor",
            mode="policy",
            scope=["tool_calls", "bogus", "raw_turns"],
            sanitization_profile={"redact_secrets": False},
            granted_by=USER,
        )
    )
    _, params = conn.calls[0]
    # scope (4th param) drops the unknown value.
    assert params[3] == ["tool_calls", "raw_turns"]
    # sanitization_profile (5th param) keeps the locked rule on.
    profile = json.loads(params[4])
    assert profile["redact_secrets"] is True


def test_capture_allowed_checks_scope() -> None:
    store = ConsentStore(_FakeDb(_Conn([])))  # type: ignore[arg-type]
    store.active_grant = AsyncMock(return_value={"scope": ["tool_calls"]})  # type: ignore[method-assign]
    assert asyncio.run(store.capture_allowed(ORG, "cursor", "tool_calls")) is True
    assert asyncio.run(store.capture_allowed(ORG, "cursor", "raw_turns")) is False

    store.active_grant = AsyncMock(return_value=None)  # type: ignore[method-assign]
    assert asyncio.run(store.capture_allowed(ORG, "cursor", "tool_calls")) is False


def test_active_grant_parses_row() -> None:
    now = datetime(2026, 5, 28, 10, 0, tzinfo=UTC)
    row = (uuid.uuid4(), "cursor", "policy", ["tool_calls"], {"redact_secrets": True},
           USER, now, None)
    store = ConsentStore(_FakeDb(_Conn([_Cur(one=row)])))  # type: ignore[arg-type]
    grant = asyncio.run(store.active_grant(ORG, "cursor"))
    assert grant is not None
    assert grant["agent"] == "cursor"
    assert grant["scope"] == ["tool_calls"]
    assert grant["expires_at"] is None


def test_list_grants_computes_status() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    rows = [
        (uuid.uuid4(), "cursor", "policy", ["tool_calls"], USER, past, None, None),
        (uuid.uuid4(), "hermes", "review", ["raw_turns"], USER, past, None, past),
        (uuid.uuid4(), "codex", "off", [], USER, past, None, None),
        (uuid.uuid4(), "claude", "policy", ["tool_calls"], USER, past, past, None),
    ]
    store = ConsentStore(_FakeDb(_Conn([_Cur(all_=rows)])))  # type: ignore[arg-type]
    grants = asyncio.run(store.list_grants(ORG))
    statuses = {g["agent"]: g["status"] for g in grants}
    assert statuses == {
        "cursor": "active",
        "hermes": "revoked",
        "codex": "off",
        "claude": "expired",
    }


def test_revoke_reports_rowcount() -> None:
    conn = _Conn([_Cur(rowcount=1)])
    store = ConsentStore(_FakeDb(conn))  # type: ignore[arg-type]
    assert asyncio.run(store.revoke(ORG, uuid.uuid4())) is True

    conn2 = _Conn([_Cur(rowcount=0)])
    store2 = ConsentStore(_FakeDb(conn2))  # type: ignore[arg-type]
    assert asyncio.run(store2.revoke(ORG, uuid.uuid4())) is False
