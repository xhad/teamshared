#!/usr/bin/env python3
"""Run conversation replay fixtures and emit a comparison dashboard.

Runs the bundled example + teamshared fixtures, writes JSON under
``eval/conversation_replay/results/``, and generates ``dashboard.html`` with the
runs embedded so you can open it directly in a browser.

Usage::

    python eval/conversation_replay_report.py
    python eval/conversation_replay_report.py --mode http   # needs TEAMSHARED_EVAL_*
    open eval/conversation_replay/results/dashboard.html
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.conversation_replay_lib import (  # noqa: E402
    format_report_table,
    load_fixture,
    replay_engine,
    replay_http,
    report_to_dict,
)

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_FIXTURES = [
    EVAL_DIR / "conversation_replay.example.yaml",
    EVAL_DIR / "conversation_replay.teamshared.yaml",
]
RESULTS_DIR = EVAL_DIR / "conversation_replay" / "results"
DASHBOARD_TEMPLATE = EVAL_DIR / "conversation_replay" / "dashboard.html"


def build_dashboard(runs: list[dict[str, Any]], *, recorded_at: str) -> str:
    template = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps({"recorded_at": recorded_at, "runs": runs}, ensure_ascii=False)
    embed = f'<script type="application/json" id="replay-data">{payload}</script>'
    marker = "<!-- REPLAY_DATA_EMBED -->"
    if marker not in template:
        raise RuntimeError("dashboard template missing REPLAY_DATA_EMBED marker")
    return template.replace(marker, embed, 1)


async def run_fixture(
    path: Path,
    *,
    mode: str,
    url: str | None,
    token: str | None,
    enrich: bool,
    token_budget: int | None,
) -> dict[str, Any]:
    fixture = load_fixture(str(path))
    if mode == "engine":
        report = await replay_engine(fixture)
    else:
        if not url or not token:
            raise SystemExit("http mode needs TEAMSHARED_EVAL_URL and TEAMSHARED_EVAL_TOKEN")
        report = await replay_http(
            fixture,
            url=url,
            token=token,
            enrich=enrich,
            token_budget=token_budget,
        )
    print(format_report_table(report))
    print()
    return report_to_dict(
        report,
        fixture,
        fixture_path=str(path),
        recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


async def main_async(args: argparse.Namespace) -> int:
    fixtures = [Path(p) for p in args.fixtures] if args.fixtures else DEFAULT_FIXTURES
    for path in fixtures:
        if not path.is_file():
            raise SystemExit(f"fixture not found: {path}")

    url = args.url or os.environ.get("TEAMSHARED_EVAL_URL")
    token = args.token or os.environ.get("TEAMSHARED_EVAL_TOKEN")
    if args.mode == "http" and (not url or not token):
        print(
            "HTTP mode needs TEAMSHARED_EVAL_URL/TOKEN; falling back to engine mode.",
            file=sys.stderr,
        )
        args.mode = "engine"

    runs: list[dict[str, Any]] = []
    for path in fixtures:
        print(f"=== {path.name} ===")
        runs.append(
            await run_fixture(
                path,
                mode=args.mode,
                url=url,
                token=token,
                enrich=not args.no_enrich,
                token_budget=args.token_budget,
            )
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = RESULTS_DIR / f"run-{stamp}.json"
    payload = {"recorded_at": stamp, "runs": runs}
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (RESULTS_DIR / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    dashboard_html = build_dashboard(runs, recorded_at=stamp)
    dash_path = RESULTS_DIR / "dashboard.html"
    dash_path.write_text(dashboard_html, encoding="utf-8")

    print(f"JSON:      {json_path}")
    print(f"Latest:    {RESULTS_DIR / 'latest.json'}")
    print(f"Dashboard: {dash_path}")
    print("Open results/dashboard.html in a browser (not the template under eval/conversation_replay/).")
    return 0 if all(run.get("passed", True) for run in runs) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        nargs="*",
        type=Path,
        help="YAML fixtures (default: example + teamshared)",
    )
    parser.add_argument("--mode", choices=["engine", "http"], default="engine")
    parser.add_argument("--url")
    parser.add_argument("--token")
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--token-budget", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
