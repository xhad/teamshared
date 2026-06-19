"""Ontology store: link validation, action parameters, seed helpers."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from teamshared.memory.autolink import apply_autolink
from teamshared.memory.ontology import OntologyError, OntologyStore

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


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
        if not self._curs:
            return _Cur()
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


def test_validate_action_parameters_missing_required() -> None:
    store = OntologyStore(_DB(_Conn([])))  # type: ignore[arg-type]
    action = {
        "parameters_schema": {"required": ["content"], "properties": {"content": {"type": "string"}}},
    }
    with pytest.raises(OntologyError, match="Missing required"):
        store.validate_action_parameters(action, {})


def test_validate_predicate_unknown() -> None:
    conn = _Conn([
        _Cur(one=(1,)),  # registry exists
        _Cur(one=None),  # predicate not found
        _Cur(many=[("mentions", "desc", [], [], "many_to_many"), ("owns", "desc", [], [], "many_to_many")]),
    ])
    store = OntologyStore(_DB(conn))  # type: ignore[arg-type]
    with pytest.raises(OntologyError, match="Unknown link predicate"):
        asyncio.run(store.validate_predicate(ORG, "invented"))


def test_validate_predicate_skips_when_registry_empty() -> None:
    conn = _Conn([_Cur(one=None)])
    store = OntologyStore(_DB(conn))  # type: ignore[arg-type]
    asyncio.run(store.validate_predicate(ORG, "anything"))


@pytest.mark.asyncio
async def test_autolink_filters_unregistered_predicates() -> None:
    from unittest.mock import AsyncMock

    mock_graph = AsyncMock()
    count = await apply_autolink(
        mock_graph,
        content="[[alice]] works at Acme",
        subject="note",
        tags=None,
        org_id=str(ORG),
        agent="cursor",
        allowed_predicates=frozenset({"mentions"}),
    )
    assert count == 1
    mock_graph.add_relation.assert_awaited_once()
    call = mock_graph.add_relation.await_args
    assert call.args[1] == "mentions"
