#!/usr/bin/env python3
"""Replay retrieval eval fixtures (NamedThingBench today; audit-log replay later)."""

from __future__ import annotations

import json
import sys

from teamshared.memory.eval_bench import (
    NAMED_THING_BENCH_MIN_MEAN_HIT_AT_5,
    run_named_thing_bench,
)


def main() -> int:
    report = run_named_thing_bench()
    print(json.dumps(report, indent=2))
    mean = report["mean_hit_at_5"]
    floor = NAMED_THING_BENCH_MIN_MEAN_HIT_AT_5
    if mean < floor:
        print(
            f"\nFAIL: mean Hit@5 {mean:.3f} below gate {floor:.2f}",
            file=sys.stderr,
        )
        return 1
    print(f"\nOK: mean Hit@5 {mean:.3f} >= gate {floor:.2f} (mean P@5 {report['mean_p_at_5']:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
