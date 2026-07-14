#!/usr/bin/env python3
"""Compare session token cost: baseline vs teamshared arms on one fixture.

Answers: *Is teamshared more expensive than not using it?*

Models cost as cumulative **input context tokens** if the LLM is invoked after
every turn (standard agent loop). Optional USD uses ``TEAMSHARED_EVAL_USD_PER_MTOK``
(default 3.0 = ~$3/M input tokens).

Arms:

- **baseline** — raw transcript (no teamshared).
- **compress** — normalize fat tool output + compress history (offline engine, or
  HTTP ``/llm/prepare`` with ``enrich=false``).
- **full** — compress + budgeted memory enrichment (HTTP only; needs server).

Usage::

    # Offline compression only (no server, no recall pack):
    python eval/conversation_replay/compare_cost.py eval/conversation_replay.example.yaml

    # Full stack vs compress-only (needs teamshared server + token):
    export TEAMSHARED_EVAL_URL=https://teamshared.com/mcp/
    export TEAMSHARED_EVAL_TOKEN=tsk_...
    python eval/conversation_replay/compare_cost.py --http eval/conversation_replay.teamshared.yaml

    # Live Cursor agent on final user turn (both arms):
    export CURSOR_API_KEY=cursor_...
    python eval/conversation_replay/compare_cost.py --http --agent eval/conversation_replay.example.yaml
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

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.conversation_replay import _run_agent_answer  # noqa: E402
from eval.conversation_replay_lib import (  # noqa: E402
    format_report_table,
    load_fixture,
    replay_engine,
    replay_http,
    report_to_dict,
    session_cost_summary,
    token_reduction_pct,
)


def _row(label: str, baseline_session: int, memory_session: int, usd: float) -> str:
    saved = token_reduction_pct(baseline_session, memory_session)
    more = " **MORE EXPENSIVE**" if memory_session > baseline_session else ""
    return (
        f"| {label} | {memory_session:,} | {saved:+.1f}% | ${usd:.4f} |{more} |"
    )


async def _main_async(args: argparse.Namespace) -> int:
    fixture = load_fixture(str(args.fixture))

    print(f"# Cost comparison: {fixture['name']}\n")

    engine_report = await replay_engine(fixture)
    engine_costs = session_cost_summary(engine_report)

    rows: list[tuple[str, Any]] = [("compress (offline)", engine_report, engine_costs)]

    compress_http_costs: dict[str, Any] | None = None
    full_costs: dict[str, Any] | None = None
    full_report = None

    if args.http:
        url = args.url or os.environ.get("TEAMSHARED_EVAL_URL")
        token = args.token or os.environ.get("TEAMSHARED_EVAL_TOKEN")
        if not url or not token:
            print(
                "--http needs TEAMSHARED_EVAL_URL and TEAMSHARED_EVAL_TOKEN",
                file=sys.stderr,
            )
            return 2

        compress_report = await replay_http(
            fixture, url=url, token=token, enrich=False, token_budget=args.token_budget
        )
        compress_http_costs = session_cost_summary(compress_report)
        rows.append(("compress (http)", compress_report, compress_http_costs))

        full_report = await replay_http(
            fixture, url=url, token=token, enrich=True, token_budget=args.token_budget
        )
        full_costs = session_cost_summary(full_report)
        rows.append(("full (compress + enrich)", full_report, full_costs))

    baseline_session = engine_costs["baseline_session_tokens"]
    baseline_usd = engine_costs["baseline_est_input_usd"]

    print("## Session cumulative input tokens")
    print()
    print("(Sum of context size after each turn — models the cost of calling the")
    print("LLM on every turn in a multi-step agent session.)\n")
    print("| arm | session tokens | vs baseline | est. input $ |")
    print("|---|---:|---:|---:|")
    print(f"| baseline (no teamshared) | {baseline_session:,} | — | ${baseline_usd:.4f} |")

    for label, _report, costs in rows:
        print(
            _row(
                label,
                baseline_session,
                costs["memory_session_tokens"],
                costs["memory_est_input_usd"],
            )
        )

    print()
    print("## Final-turn context (last row only)")
    print()
    print("| arm | final tokens | vs baseline |")
    print("|---|---:|---:|")
    print(f"| baseline | {engine_report.baseline_final_tokens:,} | — |")
    for label, report, costs in rows:
        saved = token_reduction_pct(
            engine_report.baseline_final_tokens, report.memory_final_tokens
        )
        print(f"| {label} | {report.memory_final_tokens:,} | {saved:+.1f}% |")

    print()
    print("### Interpretation")
    print()
    if full_costs and full_costs["memory_more_expensive"]:
        print("- **full** teamshared costs more on cumulative session tokens.")
    elif compress_http_costs and compress_http_costs["memory_more_expensive"]:
        print("- Compression-only still costs more cumulatively (rare — check fixture).")
    else:
        best = min(rows, key=lambda r: r[2]["memory_session_tokens"])
        print(
            f"- Cheapest teamshared arm: **{best[0]}** "
            f"({best[2]['session_token_reduction_pct']:.1f}% vs baseline session)."
        )
        if full_costs:
            enrich_overhead = (
                full_costs["memory_session_tokens"]
                - (compress_http_costs or engine_costs)["memory_session_tokens"]
            )
            if enrich_overhead > 0:
                print(
                    f"- Memory enrichment adds ~{enrich_overhead:,} session tokens "
                    f"vs compress-only."
                )
            elif enrich_overhead < 0:
                print("- Enrichment reduced session tokens vs compress-only.")

    print()
    print("Early turns often show *higher* memory tokens (enrichment pack injected")
    print("before tool output accumulates). Fat tool turns are where savings dominate.")
    print()

    agent_results: list[dict[str, Any]] = []
    if args.agent:
        if not args.http:
            print("--agent requires --http (needs live teamshared MCP).", file=sys.stderr)
            return 2
        for arm in ("baseline", "memory"):
            print(f"[agent] {arm} arm...", flush=True)
            agent_results.append(
                _run_agent_answer(fixture, arm=arm, model=args.model)
            )
        print()
        print("## Live Cursor agent (final user turn only)")
        print()
        print("| arm | success | tool calls | expect groups |")
        print("|---|---|---:|---|")
        for row in agent_results:
            print(
                f"| {row['arm']} | {'✓' if row['success'] else '✗'} | "
                f"{row['tool_calls']} | {row['matched_groups']}/{row['total_groups']} |"
            )

    if args.json:
        out = {
            "fixture": fixture["name"],
            "baseline_session_tokens": baseline_session,
            "baseline_est_input_usd": baseline_usd,
            "arms": [
                {
                    "label": label,
                    **costs,
                    "final_tokens": report.memory_final_tokens,
                    "token_reduction_pct": report.token_reduction_pct,
                }
                for label, report, costs in rows
            ],
            "agent": agent_results or None,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        print(json.dumps(out, indent=2))

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = args.out / f"cost-{fixture['name']}-{stamp}.json"
        payload = {
            "fixture": fixture["name"],
            "recorded_at": stamp,
            "reports": {
                label: report_to_dict(report, fixture, fixture_path=str(args.fixture))
                for label, report, _ in rows
            },
            "agent": agent_results or None,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {path}", file=sys.stderr)

    if full_report:
        print()
        print(format_report_table(full_report))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="YAML conversation fixture")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Also run compress-only and full enrich arms against live server",
    )
    parser.add_argument("--url", help="MCP base URL")
    parser.add_argument("--token", help="Bearer token")
    parser.add_argument("--token-budget", type=int, default=None)
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Run Cursor SDK on final user turn (baseline + memory)",
    )
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, help="Write JSON bundle to directory")
    raise SystemExit(asyncio.run(_main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
