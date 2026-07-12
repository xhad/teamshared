#!/usr/bin/env python3
"""Replay a YAML conversation transcript with vs without teamshared compression.

Compares cumulative context token cost turn-by-turn:

- **baseline** — raw message history (what burns tokens on every model call).
- **memory** — normalize fat tool outputs + compress history (engine mode), or
  the full ``POST /llm/prepare`` pipeline with optional enrichment (http mode).

Usage::

    # Offline: normalize + compress only (no server, no recall enrichment)
    python eval/conversation_replay.py eval/conversation_replay.example.yaml

    # Live server: compression + budgeted memory pack + recall probe
    export TEAMSHARED_EVAL_URL=https://teamshared.com/mcp/
    export TEAMSHARED_EVAL_TOKEN=tsk_...
    python eval/conversation_replay.py --mode http eval/conversation_replay.example.yaml

    # Optional: ask Cursor SDK to answer the final user turn both ways
  export CURSOR_API_KEY=cursor_...
    python eval/conversation_replay.py --mode http --agent eval/conversation_replay.example.yaml

See ``eval/conversation_replay.example.yaml`` for the fixture schema.
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
    parse_turns,
    replay_engine,
    replay_http,
    report_to_dict,
    score_expect_groups,
)


def _run_agent_answer(
    fixture: dict[str, Any], *, arm: str, model: str
) -> dict[str, Any]:
    """Optional final-turn agent answer via Cursor SDK (memory vs baseline)."""
    try:
        from cursor_sdk import Agent, AgentOptions, HttpMcpServerConfig, LocalAgentOptions
    except ImportError as exc:
        raise SystemExit(
            "cursor-sdk required for --agent; pip install 'teamshared[eval-agentic]'"
        ) from exc

    if "CURSOR_API_KEY" not in os.environ:
        raise SystemExit("CURSOR_API_KEY is required for --agent")

    messages = parse_turns(fixture["turns"])
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), None
    )
    if not last_user:
        raise SystemExit("fixture has no user turn for --agent")

    prompt = (
        "Answer in chat only. Do NOT create, modify, or delete files.\n\n"
        + (
            "Use teamshared memory_recall before exploring the repo.\n\n"
            if arm == "memory"
            else ""
        )
        + str(last_user)
    )

    mcp_servers = None
    if arm == "memory":
        url = os.environ.get("TEAMSHARED_EVAL_URL", "")
        token = os.environ.get("TEAMSHARED_EVAL_TOKEN", "")
        if not url or not token:
            raise SystemExit("--agent memory arm needs TEAMSHARED_EVAL_URL and TOKEN")
        mcp_servers = {
            "teamshared": HttpMcpServerConfig(
                url=url, headers={"Authorization": f"Bearer {token}"}
            )
        }

    answer_parts: list[str] = []
    tool_calls = 0
    with Agent.create(
        AgentOptions(
            model=model,
            api_key=os.environ["CURSOR_API_KEY"],
            local=LocalAgentOptions(cwd=str(REPO_ROOT)),
            mcp_servers=mcp_servers,
        )
    ) as agent:
        run = agent.send(prompt)
        for message in run.messages():
            mtype = getattr(message, "type", None)
            if mtype == "assistant":
                inner = getattr(message, "message", None)
                for block in getattr(inner, "content", None) or []:
                    text = getattr(block, "text", None)
                    if getattr(block, "type", None) == "text" and isinstance(text, str):
                        answer_parts.append(text)
            elif mtype == "tool_use":
                tool_calls += 1
        run.wait()

    answer = "\n".join(answer_parts)
    expect = fixture.get("agent_expect") or fixture.get("expect")
    success = True
    matched = 0
    total = 0
    if isinstance(expect, list) and expect:
        success, matched, total = score_expect_groups(answer, expect)

    return {
        "arm": arm,
        "success": success,
        "matched_groups": matched,
        "total_groups": total,
        "tool_calls": tool_calls,
        "answer_chars": len(answer),
        "answer_preview": answer[:400],
    }


async def _main_async(args: argparse.Namespace) -> int:
    fixture = load_fixture(str(args.fixture))
    if args.mode == "engine":
        report = await replay_engine(fixture)
    else:
        url = args.url or os.environ.get("TEAMSHARED_EVAL_URL")
        token = args.token or os.environ.get("TEAMSHARED_EVAL_TOKEN")
        if not url or not token:
            print(
                "HTTP mode needs --url/--token or TEAMSHARED_EVAL_URL/TOKEN.",
                file=sys.stderr,
            )
            return 2
        report = await replay_http(
            fixture,
            url=url,
            token=token,
            enrich=not args.no_enrich,
            token_budget=args.token_budget,
        )

    print(format_report_table(report))

    agent_results: list[dict[str, Any]] = []
    if args.agent:
        for arm in ("baseline", "memory"):
            print(f"\n[agent] running {arm} arm...", flush=True)
            agent_results.append(_run_agent_answer(fixture, arm=arm, model=args.model))

    out = report_to_dict(
        report,
        fixture,
        fixture_path=str(args.fixture),
        agent_results=agent_results or None,
        recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    if args.json:
        print(json.dumps(out, indent=2))

    if args.out:
        out_dir = args.out
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        json_path = out_dir / f"{fixture['name']}-{stamp}.json"
        json_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"Wrote {json_path}", file=sys.stderr)

    failed = False
    if report.context_expect_passed is False:
        failed = True
    if report.recall_passed is False:
        failed = True
    for row in agent_results:
        if not row.get("success"):
            failed = True
    if report.errors:
        failed = True
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="YAML conversation fixture")
    parser.add_argument(
        "--mode",
        choices=["engine", "http"],
        default="engine",
        help="engine=offline compress; http=live /llm/prepare + recall",
    )
    parser.add_argument("--url", help="MCP base URL (http mode)")
    parser.add_argument("--token", help="Bearer token (http mode)")
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="http mode: compress only, skip memory enrichment",
    )
    parser.add_argument("--token-budget", type=int, default=None)
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Run Cursor SDK on final user turn (baseline + memory)",
    )
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary")
    parser.add_argument(
        "--out",
        type=Path,
        help="Write JSON summary to this directory (one file per run)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
