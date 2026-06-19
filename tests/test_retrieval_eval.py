"""Retrieval quality tests — RRF merge and NamedThingBench fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teamshared.memory.eval_bench import (
    NAMED_THING_BENCH_MIN_MEAN_HIT_AT_5,
    run_named_thing_bench,
)
from teamshared.memory.hybrid import hit_at_k, merge_vector_keyword, precision_at_k
from teamshared.memory.types import MemoryRecord

_FIXTURE = Path(__file__).parent / "eval" / "named_thing_bench.json"


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
    data = json.loads(_FIXTURE.read_text())
    assert len(data["cases"]) >= 10


def test_bench_vector_only_baseline() -> None:
    """Sanity: RRF should not drop expected id when it appears in vector list."""
    cases = json.loads(_FIXTURE.read_text())["cases"]
    for case in cases:
        vec = [_rec(mid, 1.0 - i * 0.1) for i, mid in enumerate(case["candidates"])]
        kw = [_rec(mid, 0.5) for mid in case.get("keyword_only", [])]
        merged = merge_vector_keyword(vec, kw)
        top_ids = [r.id for r in merged[:5]]
        assert hit_at_k(top_ids, case["expected_ids"], k=5) >= case.get("min_hit_at_5", 1.0), case["name"]


def test_named_thing_bench_ci_gate() -> None:
    """CI hard gate — mean Hit@5 on the synthetic NamedThingBench fixture."""
    report = run_named_thing_bench(_FIXTURE)
    assert report["case_count"] >= 10
    assert report["mean_hit_at_5"] >= NAMED_THING_BENCH_MIN_MEAN_HIT_AT_5
