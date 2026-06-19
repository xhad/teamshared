"""Tests for zero-LLM graph autolink extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teamshared.memory.autolink import apply_autolink, extract_entity_refs


def test_extract_wikilinks() -> None:
    refs = extract_entity_refs("Met [[alice]] and [[bob]]", subject="meeting")
    preds = {(r.subject, r.predicate, r.object_) for r in refs}
    assert ("meeting", "mentions", "alice") in preds
    assert ("meeting", "mentions", "bob") in preds


def test_extract_works_at() -> None:
    refs = extract_entity_refs("Alice works at Acme AI")
    assert any(r.predicate == "works_at" and r.object_ == "Acme AI" for r in refs)


def test_extract_repo_tag() -> None:
    refs = extract_entity_refs("note", subject="teamshared", tags=["repo:Users-chad-code-teamshared"])
    assert any(r.predicate == "works_on" for r in refs)


@pytest.mark.asyncio
async def test_apply_autolink_writes_edges() -> None:
    graph = AsyncMock()
    count = await apply_autolink(
        graph,
        content="[[alice]] works at Acme",
        subject="note",
        tags=None,
        org_id="00000000-0000-0000-0000-000000000001",
        agent="cursor",
    )
    assert count >= 1
    graph.add_relation.assert_awaited()


@pytest.mark.asyncio
async def test_apply_autolink_no_graph() -> None:
    assert await apply_autolink(
        None,
        content="[[alice]]",
        subject=None,
        tags=None,
        org_id="x",
        agent="cursor",
    ) == 0
