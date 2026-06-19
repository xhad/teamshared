"""Tests for gap detection and synthesis helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from teamshared.memory.think import detect_gaps, synthesize
from teamshared.memory.types import MemoryRecord


def _rec(
    *,
    id_: str = "m1",
    content: str = "Alice works at Acme",
    subject: str | None = "alice",
    age_days: int = 1,
    confidence: float | None = 0.9,
) -> MemoryRecord:
    return MemoryRecord(
        id=id_,
        pillar="semantic",
        content=content,
        subject=subject,
        confidence=confidence,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


def test_detect_gaps_empty_records() -> None:
    gaps = detect_gaps("meeting with Alice", [])
    assert len(gaps) == 1
    assert gaps[0].kind == "missing"


def test_detect_gaps_stale() -> None:
    gaps = detect_gaps("alice", [_rec(age_days=60)])
    kinds = {g.kind for g in gaps}
    assert "stale" in kinds


def test_detect_gaps_contradiction_on_subject() -> None:
    gaps = detect_gaps(
        "alice",
        [
            _rec(id_="a", content="Alice prefers Python", subject="alice"),
            _rec(id_="b", content="Alice banned Python entirely", subject="alice"),
        ],
    )
    assert any(g.kind == "contradicts" for g in gaps)


@pytest.mark.asyncio
async def test_synthesize_fallback_without_llm() -> None:
    settings = AsyncMock()
    with patch(
        "teamshared.memory.think.think_compose",
        AsyncMock(side_effect=RuntimeError("no llm")),
    ):
        result = await synthesize(
            settings,
            query="who is Alice",
            records=[_rec()],
            token_budget=500,
        )
    assert "Alice" in result.answer_md or "alice" in result.answer_md.lower()
    assert result.sources_used >= 1


@pytest.mark.asyncio
async def test_synthesize_appends_gap_block() -> None:
    settings = AsyncMock()
    with patch(
        "teamshared.memory.think.think_compose",
        AsyncMock(return_value={"answer_md": "Alice runs engineering.", "citations": []}),
    ):
        result = await synthesize(
            settings,
            query="Alice",
            records=[_rec(age_days=90)],
            token_budget=500,
        )
    assert "Heads up" in result.answer_md or result.gaps
