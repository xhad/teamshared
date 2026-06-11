"""A/B agentic evaluation: does teamshared memory help coding agents?

Runs each task in eval/agentic/tasks.yaml through the Cursor SDK twice per
trial -- once with the teamshared MCP server attached ("memory" arm) and once
without ("baseline" arm) -- then scores the answers and compares success rate,
wall time, assistant turns, and tool calls.

Requirements::

    pip install 'teamshared[eval-agentic]'   # cursor-sdk
    export CURSOR_API_KEY=cursor_...
    export TEAMSHARED_EVAL_URL=https://teamshared.com/mcp/
    export TEAMSHARED_EVAL_TOKEN=tsk_...

Usage::

    python eval/agentic/runner.py --trials 5
    python eval/agentic/runner.py --arms baseline --tasks integration-tests
    python eval/agentic/runner.py --report eval/agentic/results/run-*.jsonl

Each trial is a fresh agent (no conversation carry-over), run locally against
this repo checkout. Agents are instructed not to modify files; results land in
eval/agentic/results/ as JSONL plus a printed markdown summary.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from cursor_sdk import (
        Agent,
        AgentOptions,
        CursorAgentError,
        HttpMcpServerConfig,
        LocalAgentOptions,
    )
except ImportError:  # pragma: no cover - guard for environments without the SDK
    Agent = None  # type: ignore[assignment,misc]

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_FILE = Path(__file__).resolve().parent / "tasks.yaml"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

GUARDRAIL = (
    "Answer in chat only. Do NOT create, modify, or delete any files, and do "
    "not run commands that change system state.\n\n"
)
MEMORY_PREAMBLE = (
    "You have access to the team's shared memory via the teamshared MCP "
    "server. Before exploring the repository, call memory_recall with the "
    "question to check for relevant team knowledge, and ground your answer "
    "in what you find.\n\n"
)


@dataclass
class Trial:
    task: str
    arm: str
    trial: int
    control: bool
    success: bool
    matched_groups: int
    total_groups: int
    duration_s: float
    assistant_messages: int
    tool_calls: int
    answer_chars: int
    error: str | None = None


def load_tasks(path: Path, only: list[str] | None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = yaml.safe_load(path.read_text())["tasks"]
    if only:
        tasks = [t for t in tasks if t["name"] in only]
        missing = set(only) - {t["name"] for t in tasks}
        if missing:
            raise SystemExit(f"unknown task(s): {', '.join(sorted(missing))}")
    return tasks


def score(answer: str, expect: list[list[str]]) -> tuple[bool, int]:
    lowered = answer.lower()
    matched = sum(
        1 for group in expect if any(alt.lower() in lowered for alt in group)
    )
    return matched == len(expect), matched


def memory_mcp() -> dict[str, HttpMcpServerConfig]:
    url = os.environ.get("TEAMSHARED_EVAL_URL", "")
    token = os.environ.get("TEAMSHARED_EVAL_TOKEN", "")
    if not url or not token:
        raise SystemExit(
            "memory arm needs TEAMSHARED_EVAL_URL and TEAMSHARED_EVAL_TOKEN"
        )
    return {
        "teamshared": HttpMcpServerConfig(
            url=url, headers={"Authorization": f"Bearer {token}"}
        )
    }


def run_trial(task: dict[str, Any], arm: str, trial: int, model: str) -> Trial:
    prompt = GUARDRAIL + task["prompt"]
    mcp_servers: dict[str, HttpMcpServerConfig] | None = None
    if arm == "memory":
        prompt = GUARDRAIL + MEMORY_PREAMBLE + task["prompt"]
        mcp_servers = memory_mcp()

    assistant_messages = 0
    tool_calls = 0
    answer_parts: list[str] = []
    started = time.perf_counter()
    error: str | None = None
    try:
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
                # Duck-typed: the SDK message union evolves between releases.
                mtype = getattr(message, "type", None)
                if mtype == "assistant":
                    assistant_messages += 1
                    inner = getattr(message, "message", None)
                    for block in getattr(inner, "content", None) or []:
                        text = getattr(block, "text", None)
                        if getattr(block, "type", None) == "text" and isinstance(text, str):
                            answer_parts.append(text)
                elif mtype == "tool_use":
                    tool_calls += 1
            run.wait()
    except CursorAgentError as exc:
        error = f"startup: {exc}"
    except Exception as exc:  # record the failure, don't abort the matrix
        error = f"run: {exc}"

    duration = time.perf_counter() - started
    answer = "\n".join(answer_parts)
    success, matched = (False, 0) if error else score(answer, task["expect"])
    return Trial(
        task=task["name"],
        arm=arm,
        trial=trial,
        control=bool(task.get("control", False)),
        success=success,
        matched_groups=matched,
        total_groups=len(task["expect"]),
        duration_s=round(duration, 2),
        assistant_messages=assistant_messages,
        tool_calls=tool_calls,
        answer_chars=len(answer),
        error=error,
    )


def _med(vals: list[float] | list[int]) -> str:
    return f"{statistics.median(vals):.1f}" if vals else "-"


def summarize(trials: list[Trial]) -> str:
    lines = [
        "| task | arm | success | p50 time (s) | p50 turns | p50 tool calls | n |",
        "|---|---|---|---|---|---|---|",
    ]
    keys = sorted({(t.task, t.arm) for t in trials})
    for task, arm in keys:
        group = [t for t in trials if t.task == task and t.arm == arm]
        ok = [t for t in group if t.error is None]
        rate = sum(t.success for t in group) / len(group)
        ctl = " (control)" if group[0].control else ""
        lines.append(
            f"| {task}{ctl} | {arm} | {rate:.0%} "
            f"| {_med([t.duration_s for t in ok])} "
            f"| {_med([t.assistant_messages for t in ok])} "
            f"| {_med([t.tool_calls for t in ok])} | {len(group)} |"
        )
    return "\n".join(lines)


def report(paths: list[str]) -> None:
    trials: list[Trial] = []
    for pattern in paths:
        for path in glob.glob(pattern):
            with open(path) as fh:
                trials.extend(Trial(**json.loads(line)) for line in fh)
    if not trials:
        raise SystemExit("no trial records found")
    print(summarize(trials))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3, help="Trials per task per arm.")
    parser.add_argument(
        "--arms", default="both", choices=["both", "memory", "baseline"]
    )
    parser.add_argument("--tasks", nargs="*", help="Subset of task names.")
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument(
        "--report", nargs="*", help="Skip running; aggregate existing JSONL file(s)."
    )
    args = parser.parse_args()

    if args.report:
        report(args.report)
        return

    if Agent is None:
        raise SystemExit(
            "cursor-sdk is not installed; pip install 'teamshared[eval-agentic]'"
        )
    if "CURSOR_API_KEY" not in os.environ:
        raise SystemExit("CURSOR_API_KEY is required")

    arms = ["memory", "baseline"] if args.arms == "both" else [args.arms]
    if "memory" in arms:
        memory_mcp()  # fail fast on missing env before burning trials

    tasks = load_tasks(TASKS_FILE, args.tasks)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"run-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    trials: list[Trial] = []
    with open(out_path, "w") as fh:
        for task in tasks:
            for trial_no in range(1, args.trials + 1):
                for arm in arms:
                    print(
                        f"[{task['name']}] arm={arm} trial={trial_no}/{args.trials}...",
                        flush=True,
                    )
                    result = run_trial(task, arm, trial_no, args.model)
                    trials.append(result)
                    fh.write(json.dumps(asdict(result)) + "\n")
                    fh.flush()
                    status = "ok" if result.success else (result.error or "miss")
                    print(
                        f"  -> {status} in {result.duration_s}s "
                        f"({result.assistant_messages} turns, "
                        f"{result.tool_calls} tool calls)"
                    )

    print(f"\nresults: {out_path}\n")
    print(summarize(trials))
    failures = [t for t in trials if t.error]
    if failures:
        print(f"\n{len(failures)} trial(s) errored; inspect the JSONL.", file=sys.stderr)


if __name__ == "__main__":
    main()
