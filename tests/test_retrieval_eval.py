"""Retrieval quality tests — RRF merge and NamedThingBench fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teamshared.memory.hybrid import hit_at_k, merge_vector_keyword, precision_at_k
from teamshared.memory.types import MemoryRecord


def _rec(id_: str, score: float) -> MemoryRecord:
    return MemoryRecord(id=id_, pillar="semantic", content=id_, score=score)


def test_rrf_promotes_dual_list_hits() -> None:
    vec = [_rec("a", 0.9), _rec("b", 0.8)]
    kw = [_rec("b", 0.7), _rec("c", 0.6)]
    merged = merge_vector_keyword(vec, kw)
    assert merged[0].id == "b"


def test_precision_at_k() -> None:
    assert precision_at_k(["a", "b", "c"], ["a", "c"], k=5) == pytest.approx(0.4)


def test_named_thing_bench_fixture_loads() -> None:
    path = Path(__file__).parent / "eval" / "named_thing_bench.json"
    data = json.loads(path.read_text())
    assert len(data["cases"]) >= 3


def test_bench_vector_only_baseline() -> None:
    """Sanity: RRF should not drop expected id when it appears in vector list."""
    path = Path(__file__).parent / "eval" / "named_thing_bench.json"
    cases = json.loads(path.read_text())["cases"]
    for case in cases[:3]:
        vec = [_rec(mid, 1.0 - i * 0.1) for i, mid in enumerate(case["candidates"])]
        kw = [_rec(mid, 0.5) for mid in case.get("keyword_only", [])]
        merged = merge_vector_keyword(vec, kw)
        top_ids = [r.id for r in merged[:5]]
        assert hit_at_k(top_ids, case["expected_ids"], k=5) >= case.get("min_hit_at_5", 1.0), case["name"]
