"""Tests for the context assembler.

Two layers:
- Pure helpers (``plan_queries``, ``pack_records``, ``render_pack``) with no I/O.
- :class:`ContextAssembler` over a mocked :class:`MemoryFacade`, asserting it
  fans recall + graph out in parallel, merges, token-budgets, and renders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from teamshared.identity.principal import Principal
from teamshared.memory.context_assembler import (
    ContextAssembler,
    estimate_tokens,
    pack_records,
    plan_queries,
    render_pack,
)
from teamshared.memory.types import MemoryRecord, RecallResult

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _rec(rid: str, pillar: str, content: str, **kw) -> MemoryRecord:
    return MemoryRecord(id=rid, pillar=pillar, content=content, **kw)  # type: ignore[arg-type]


def test_estimate_tokens_is_ceil_of_chars_over_four() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_plan_queries_extracts_entities_from_open_files() -> None:
    plan = plan_queries(
        "  fix the retrieval bug  ",
        ["src/teamshared/memory/retrieval.py", "tests/test_recall_ranking.py"],
    )
    assert plan.primary == "fix the retrieval bug"
    # base name and stem are both candidates, deduped, capped at 5.
    assert "retrieval.py" in plan.entities
    assert "retrieval" in plan.entities
    assert len(plan.entities) <= 5


def test_pack_records_respects_budget_but_keeps_first() -> None:
    records = [_rec(f"m{i}", "semantic", "x" * 200) for i in range(10)]
    kept, used = pack_records(records, token_budget=60)
    # Each snippet ~ 200 chars => ~51 tokens; budget 60 keeps only the first.
    assert len(kept) == 1
    assert used > 0

    # A huge first record alone still yields a non-empty pack.
    big = [_rec("big", "semantic", "y" * 10000)]
    kept_big, _ = pack_records(big, token_budget=10)
    assert len(kept_big) == 1


def test_render_pack_groups_by_pillar_with_graph_section() -> None:
    records = [
        _rec("p1", "procedural", "run the ship-pr playbook"),
        _rec("s1", "semantic", "imports go at the top", agent="cursor"),
        _rec("graph:ServiceB", "semantic", "A --[depends_on]--> ServiceB"),
    ]
    out = render_pack("do a thing", records)
    assert out.startswith("# Context for: do a thing")
    assert "## Procedural" in out
    assert "## Semantic" in out
    assert "## Graph" in out
    # Procedural renders before Semantic per _PILLAR_ORDER.
    assert out.index("## Procedural") < out.index("## Semantic")
    # Graph record is filed under Graph, not Semantic.
    assert "A --[depends_on]--> ServiceB" in out


def test_render_pack_empty_says_so() -> None:
    out = render_pack("nothing here", [])
    assert "No relevant team memory found" in out


async def test_assembler_merges_recall_and_graph_in_one_pack() -> None:
    principal = Principal(org_id=ORG, type="agent", id=uuid.uuid4(), display="cursor")

    recall_records = [
        _rec("s1", "semantic", "use pgvector not pinecone", agent="cursor",
             created_at=datetime.now(UTC), confidence=0.9),
        _rec("e1", "episodic", "tried X on tuesday, failed"),
    ]
    graph_records = [_rec("graph:ServiceB", "semantic", "A --[depends_on]--> ServiceB")]

    facade = MagicMock()
    facade.recall = AsyncMock(
        return_value=RecallResult(
            query="q", records=recall_records, counts_by_pillar={"semantic_episodic": 2}
        )
    )
    facade.graph = MagicMock()
    facade.graph.related = AsyncMock(return_value=graph_records)

    assembler = ContextAssembler(facade)
    pack = await assembler.assemble(
        principal,
        task="where should the assembler live?",
        repo="home-chad-code-teamshared",
        github="xhad/teamshared",
        open_files=["src/teamshared/memory/facade.py"],
        token_budget=4000,
        caller_agent="cursor",
    )

    # recall was driven by the secure path with repo/github boost + shared brain.
    rkw = facade.recall.await_args.kwargs
    assert rkw["repo"] == "home-chad-code-teamshared"
    assert rkw["github"] == "xhad/teamshared"
    assert rkw["agent_filter"] is None
    assert rkw["caller_agent"] == "cursor"

    assert pack.counts_by_pillar["graph"] == 1
    assert pack.tokens_used > 0
    assert len(pack.records) == 3
    assert "## Graph" in pack.rendered
    assert "pgvector" in pack.rendered


async def test_assembler_tolerates_disabled_graph() -> None:
    principal = Principal(org_id=ORG, type="agent", id=uuid.uuid4(), display="cursor")
    facade = MagicMock()
    facade.recall = AsyncMock(
        return_value=RecallResult(query="q", records=[], counts_by_pillar={})
    )
    facade.graph = None

    assembler = ContextAssembler(facade)
    pack = await assembler.assemble(principal, task="anything", open_files=["a.py"])

    assert "graph" not in pack.counts_by_pillar
    assert "No relevant team memory found" in pack.rendered


async def test_assembler_survives_graph_error() -> None:
    principal = Principal(org_id=ORG, type="agent", id=uuid.uuid4(), display="cursor")
    facade = MagicMock()
    facade.recall = AsyncMock(
        return_value=RecallResult(
            query="q",
            records=[_rec("s1", "semantic", "a fact")],
            counts_by_pillar={"semantic_episodic": 1},
        )
    )
    facade.graph = MagicMock()
    facade.graph.related = AsyncMock(side_effect=RuntimeError("neo4j down"))

    assembler = ContextAssembler(facade)
    pack = await assembler.assemble(principal, task="x", open_files=["a.py"])

    # graph blew up but the pack still has the recall record.
    assert "graph" not in pack.counts_by_pillar
    assert len(pack.records) == 1
