"""NamedThingBench — synthetic RRF ranking gate for CI.

Exercises hybrid merge ranking on fixture cases until end-to-end recall eval
against a seeded corpus lands (see ``scripts/eval_replay.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from teamshared.memory.hybrid import hit_at_k, merge_vector_keyword, precision_at_k
from teamshared.memory.types import MemoryRecord

# GBrain gap Phase 3: gate Hit@5 (each case has one expected id in top-5).
# Mean P@5 caps at 0.2 for single-relevant cases with k=5 — use hit rate for CI.
NAMED_THING_BENCH_MIN_MEAN_HIT_AT_5 = 1.0
# Informational only; not used as CI gate for single-relevant fixtures.
NAMED_THING_BENCH_MIN_MEAN_P_AT_5 = 0.40

_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "eval" / "named_thing_bench.json"
)


def _rec(id_: str, score: float) -> MemoryRecord:
    return MemoryRecord(id=id_, pillar="semantic", content=id_, score=score)


def run_named_thing_bench(
    fixture_path: Path | None = None,
    *,
    k: int = 5,
) -> dict[str, Any]:
    """Score every fixture case via RRF merge; return per-case + aggregate metrics."""
    path = fixture_path or _DEFAULT_FIXTURE
    cases: list[dict[str, Any]] = json.loads(path.read_text())["cases"]
    results: list[dict[str, Any]] = []
    p_at_k: list[float] = []
    hit_at_k_scores: list[float] = []

    for case in cases:
        vec = [_rec(mid, 1.0 - i * 0.1) for i, mid in enumerate(case["candidates"])]
        kw = [_rec(mid, 0.5) for mid in case.get("keyword_only", [])]
        merged = merge_vector_keyword(vec, kw)
        top_ids = [r.id for r in merged[:k]]
        p = precision_at_k(top_ids, case["expected_ids"], k=k)
        hit = hit_at_k(top_ids, case["expected_ids"], k=k)
        p_at_k.append(p)
        hit_at_k_scores.append(hit)
        results.append(
            {
                "name": case["name"],
                "p_at_k": p,
                "hit_at_k": hit,
                "top_ids": top_ids,
            }
        )

    count = len(p_at_k) or 1
    return {
        "cases": results,
        "mean_p_at_5": sum(p_at_k) / count,
        "mean_hit_at_5": sum(hit_at_k_scores) / count,
        "case_count": len(results),
        "fixture": str(path),
        "gate_metric": "mean_hit_at_5",
        "gate_floor": NAMED_THING_BENCH_MIN_MEAN_HIT_AT_5,
    }
