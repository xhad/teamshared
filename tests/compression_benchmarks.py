"""Realistic payloads and token-savings metrics for compression integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from teamshared.memory.context_assembler import estimate_tokens

EndpointKind = Literal["messages", "normalize"]


@dataclass(frozen=True)
class CompressionScenario:
    """One benchmark case with minimum expected savings."""

    name: str
    kind: EndpointKind
    # For kind=messages: chat messages list. For normalize: tool output string.
    payload: Any
    tool_name: str = "Shell"
    min_token_reduction_pct: float = 0.0
    min_chars_saved: int = 0
    expect_compressed: bool = False
    expect_cleaned: bool = False
    expect_unchanged: bool = False


def token_estimate_for_messages(messages: list[dict[str, Any]]) -> int:
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
    return estimate_tokens("\n".join(parts))


def token_estimate_for_text(text: str) -> int:
    return estimate_tokens(text)


def token_reduction_pct(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round(100.0 * (before - after) / before, 2)


@dataclass
class SavingsReport:
    scenario: str
    original_chars: int
    result_chars: int
    original_tokens: int
    result_tokens: int
    token_reduction_pct: float
    chars_saved: int
    compressed: bool
    cleaned: bool = False
    ref: str | None = None

    def assert_meets(self, scenario: CompressionScenario) -> None:
        if scenario.expect_unchanged:
            assert self.token_reduction_pct == 0.0, (
                f"{scenario.name}: expected no token reduction, got {self.token_reduction_pct}%"
            )
            return
        assert self.token_reduction_pct >= scenario.min_token_reduction_pct, (
            f"{scenario.name}: token reduction {self.token_reduction_pct}% "
            f"< min {scenario.min_token_reduction_pct}% "
            f"({self.original_tokens} -> {self.result_tokens} tokens)"
        )
        assert self.chars_saved >= scenario.min_chars_saved, (
            f"{scenario.name}: chars_saved {self.chars_saved} < min {scenario.min_chars_saved}"
        )
        if scenario.expect_compressed:
            assert self.compressed, f"{scenario.name}: expected compressed=true"
        if scenario.expect_cleaned:
            assert self.cleaned, f"{scenario.name}: expected cleaned=true"


def _grep_json_rows(count: int) -> str:
    rows = [
        {
            "line": i + 1,
            "path": f"src/module/file_{i % 40}.py",
            "match": f"def handler_{i}(): return {i}",
        }
        for i in range(count)
    ]
    return json.dumps(rows, separators=(",", ":"))


def _error_log_lines(count: int) -> str:
    lines: list[str] = []
    for i in range(count):
        if i % 17 == 0:
            lines.append(f"[ERROR] worker-{i % 5}: connection reset by peer at step {i}")
        elif i % 23 == 0:
            lines.append(f"[WARN] retry {i}: backing off 200ms")
        else:
            lines.append(f"[INFO] processed batch {i} ok")
    return "\n".join(lines)


def _memory_recall_payload(records: int, content_chars: int) -> str:
    payload = {
        "query": "deployment migrations",
        "records": [
            {
                "id": f"mem-{i}",
                "pillar": "semantic" if i % 2 else "episodic",
                "agent": "cursor",
                "content": f"fact-{i}: " + ("x" * content_chars),
                "embedding": [0.01 * (i % 10)] * 32,
                "metadata": {"score": 0.9 - i * 0.01, "source": "vector"},
            }
            for i in range(records)
        ],
        "counts_by_pillar": {"semantic": records // 2, "episodic": records - records // 2},
    }
    return json.dumps(payload, separators=(",", ":"))


def _teamshared_context_block() -> str:
    return (
        "## TeamShared context\n\n"
        "# Context for: deploy\n\n"
        "## Skill\n"
        + "".join(f"- skill-{i} (v1): run step {i}\n" for i in range(12))
        + "\n## Semantic\n- [[teamshared]] migrations use `make migrate`\n"
    )


def _multi_turn_tool_thread() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": "find failing tests in the repo"},
        {"role": "assistant", "content": "I'll grep for FAIL markers."},
        {"role": "tool", "content": _grep_json_rows(300)},
        {"role": "tool", "content": _error_log_lines(120)},
        {"role": "assistant", "content": "Found several failures in module handlers."},
    ]


def compression_scenarios() -> list[CompressionScenario]:
    """Scenarios representing common agent context bloat."""
    return [
        CompressionScenario(
            name="grep_json_500_rows",
            kind="messages",
            payload=[{"role": "tool", "content": _grep_json_rows(500)}],
            min_token_reduction_pct=75.0,
            min_chars_saved=8000,
            expect_compressed=True,
        ),
        CompressionScenario(
            name="error_log_200_lines",
            kind="messages",
            payload=[{"role": "tool", "content": _error_log_lines(200)}],
            min_token_reduction_pct=35.0,
            min_chars_saved=1500,
            expect_compressed=True,
        ),
        CompressionScenario(
            name="memory_recall_normalize",
            kind="normalize",
            tool_name="MCP:memory_recall",
            payload=_memory_recall_payload(records=15, content_chars=1200),
            min_token_reduction_pct=55.0,
            min_chars_saved=10000,
            expect_cleaned=True,
        ),
        CompressionScenario(
            name="multi_turn_tool_thread",
            kind="messages",
            payload=_multi_turn_tool_thread(),
            min_token_reduction_pct=50.0,
            min_chars_saved=5000,
            expect_compressed=True,
        ),
        CompressionScenario(
            name="short_tool_output_passthrough",
            kind="messages",
            payload=[{"role": "tool", "content": "ok: 3 files changed"}],
            expect_unchanged=True,
        ),
        CompressionScenario(
            name="teamshared_context_protected",
            kind="messages",
            payload=[
                {"role": "system", "content": _teamshared_context_block()},
                {"role": "user", "content": "deploy"},
            ],
            expect_unchanged=True,
        ),
        CompressionScenario(
            name="teamshared_context_normalize_protected",
            kind="normalize",
            tool_name="MCP:memory_recall",
            payload=_teamshared_context_block(),
            expect_unchanged=True,
        ),
    ]


def format_savings_table(reports: list[SavingsReport]) -> str:
    header = (
        f"{'scenario':<32} {'orig_tok':>8} {'new_tok':>8} {'saved%':>7} "
        f"{'chars':>8} {'cmp':>4} {'cln':>4}"
    )
    lines = [header, "-" * len(header)]
    for r in reports:
        lines.append(
            f"{r.scenario:<32} {r.original_tokens:>8} {r.result_tokens:>8} "
            f"{r.token_reduction_pct:>6.1f}% {r.chars_saved:>8} "
            f"{'yes' if r.compressed else 'no':>4} "
            f"{'yes' if r.cleaned else 'no':>4}"
        )
    return "\n".join(lines)
