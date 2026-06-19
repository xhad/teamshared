#!/usr/bin/env python3
"""Replay retrieval eval fixtures (NamedThingBench today; audit-log replay later)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from teamshared.memory.eval_bench import (
    NAMED_THING_BENCH_MIN_MEAN_P_AT_5,
    run_named_thing_bench,
)


def main() -> int:
    report = run_named_thing_bench()
    print(json.dumps(report, indent=2))
    mean = report["mean_p_at_5"]
    floor = NAMED_THING_BENCH_MIN_MEAN_P_AT_5
    if mean < floor:
        print(
            f"\nFAIL: mean P@5 {mean:.3f} below gate {floor:.2f}",
            file=sys.stderr,
        )
        return 1
    print(f"\nOK: mean P@5 {mean:.3f} >= gate {floor:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
