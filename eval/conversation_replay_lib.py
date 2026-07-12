"""Shared logic for conversation replay A/B (baseline vs teamshared)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

from teamshared.compress.ccr_store import org_scope_from_id
from teamshared.compress.engine import compress_messages, compress_messages_with_ccr
from teamshared.compress.factory import ccr_store_from_working
from teamshared.compress.tool_output import normalize_tool_output
from teamshared.config import Settings, get_settings
from teamshared.memory.context_assembler import estimate_tokens
from teamshared.memory.working import WorkingMemory

# Optional generators for fat tool payloads in fixtures (see example YAML).
_GENERATORS: dict[str, Any] = {}


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
    }
    return json.dumps(payload, separators=(",", ":"))


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


_GENERATORS = {
    "grep_json_500": lambda: _grep_json_rows(500),
    "grep_json_300": lambda: _grep_json_rows(300),
    "memory_recall_fat": lambda: _memory_recall_payload(15, 1200),
    "error_log_200": lambda: _error_log_lines(200),
}


def load_fixture(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("fixture root must be a mapping")
    if not data.get("name"):
        raise ValueError("fixture requires name")
    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("fixture requires a non-empty turns list")
    return data


def _expand_generated(value: str) -> str:
    factory = _GENERATORS.get(value)
    if factory is None:
        raise ValueError(f"unknown generate key: {value!r}")
    return factory()


def parse_turns(raw_turns: list[Any]) -> list[dict[str, Any]]:
    """Normalize YAML turns into OpenAI-style messages with optional tool_name."""
    messages: list[dict[str, Any]] = []
    for item in raw_turns:
        if not isinstance(item, dict):
            raise ValueError(f"each turn must be a mapping, got {type(item).__name__}")

        if "user" in item:
            messages.append({"role": "user", "content": str(item["user"])})
            continue
        if "assistant" in item:
            messages.append({"role": "assistant", "content": str(item["assistant"])})
            continue
        if "system" in item:
            messages.append({"role": "system", "content": str(item["system"])})
            continue

        tool = item.get("tool")
        if isinstance(tool, dict):
            name = str(tool.get("name") or "Shell")
            if "generate" in tool:
                content = _expand_generated(str(tool["generate"]))
            elif "output" in tool:
                content = str(tool["output"])
            elif "content" in tool:
                content = str(tool["content"])
            else:
                raise ValueError("tool turn needs output, content, or generate")
            messages.append({"role": "tool", "content": content, "tool_name": name})
            continue

        if "role" in item and "content" in item:
            msg: dict[str, Any] = {
                "role": str(item["role"]),
                "content": str(item["content"]),
            }
            if item.get("tool_name"):
                msg["tool_name"] = str(item["tool_name"])
            messages.append(msg)
            continue

        raise ValueError(f"unrecognized turn shape: {sorted(item.keys())}")
    return messages


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def token_count_messages(
    messages: list[dict[str, Any]], *, additional_context: str | None = None
) -> int:
    parts = [message_text(m.get("content")) for m in messages]
    if additional_context:
        parts.append(additional_context)
    return estimate_tokens("\n".join(parts))


def token_reduction_pct(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round(100.0 * (before - after) / before, 2)


def score_expect_groups(text: str, expect: list[list[str]]) -> tuple[bool, int, int]:
    lowered = text.lower()
    matched = sum(
        1 for group in expect if any(alt.lower() in lowered for alt in group)
    )
    return matched == len(expect), matched, len(expect)


def score_expect_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _body_to_content(body: Any) -> str:
    if isinstance(body, str):
        return body
    return json.dumps(body, separators=(",", ":"), default=str)


@dataclass
class Checkpoint:
    turn: int
    baseline_tokens: int
    memory_tokens: int


@dataclass
class ReplayReport:
    name: str
    mode: str
    turn_count: int
    checkpoints: list[Checkpoint] = field(default_factory=list)
    baseline_final_tokens: int = 0
    memory_final_tokens: int = 0
    memory_enriched_tokens: int | None = None
    token_reduction_pct: float = 0.0
    enriched_reduction_pct: float | None = None
    recall_passed: bool | None = None
    context_expect_passed: bool | None = None
    additional_context: str | None = None
    errors: list[str] = field(default_factory=list)


async def _normalize_history(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    org_scope: str,
    store: Any,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") != "tool":
            out.append(dict(msg))
            continue
        tool_name = str(msg.get("tool_name") or "Shell")
        normalized = await normalize_tool_output(
            settings,
            tool_name,
            msg.get("content", ""),
            org_scope=org_scope,
            store=store,
        )
        out.append(
            {
                "role": "tool",
                "content": _body_to_content(normalized.body),
                **({"tool_name": tool_name} if tool_name else {}),
            }
        )
    return out


async def _compress_history(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    org_scope: str,
    store: Any | None,
) -> list[dict[str, Any]]:
    if store is not None:
        result = await compress_messages_with_ccr(
            settings, messages, org_scope=org_scope, store=store
        )
    else:
        result = compress_messages(settings, messages)
    return result.messages


async def replay_engine(
    fixture: dict[str, Any],
    *,
    settings: Settings | None = None,
    working: WorkingMemory | None = None,
    org_id: str = "eval-replay",
) -> ReplayReport:
    """Baseline vs normalize+compress (no live recall enrichment)."""
    settings = settings or get_settings()
    messages = parse_turns(fixture["turns"])
    report = ReplayReport(
        name=str(fixture["name"]),
        mode="engine",
        turn_count=len(messages),
    )

    if working is None:
        working = WorkingMemory(settings.redis_url, default_ttl=settings.session_ttl)
        store: Any | None = None
        close_working = True
        try:
            await working.connect()
            store = ccr_store_from_working(settings, working)
        except Exception:
            await working.close()
            working = None
            close_working = False
    else:
        close_working = False
        store = ccr_store_from_working(settings, working)

    org_scope = org_scope_from_id(org_id)

    try:
        history: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages, start=1):
            history.append(dict(msg))
            baseline_tokens = token_count_messages(history)
            normalized = await _normalize_history(
                settings, history, org_scope=org_scope, store=store
            )
            compressed_messages = await _compress_history(
                settings, normalized, org_scope=org_scope, store=store
            )
            memory_tokens = token_count_messages(compressed_messages)
            report.checkpoints.append(
                Checkpoint(
                    turn=idx,
                    baseline_tokens=baseline_tokens,
                    memory_tokens=memory_tokens,
                )
            )

        report.baseline_final_tokens = report.checkpoints[-1].baseline_tokens
        report.memory_final_tokens = report.checkpoints[-1].memory_tokens
        report.token_reduction_pct = token_reduction_pct(
            report.baseline_final_tokens, report.memory_final_tokens
        )
        # context_expect_any needs live enrichment (http mode); engine is compress-only.
    finally:
        if close_working and working is not None:
            await working.close()

    return report


async def replay_http(
    fixture: dict[str, Any],
    *,
    url: str,
    token: str,
    enrich: bool = True,
    token_budget: int | None = None,
) -> ReplayReport:
    """Baseline vs normalize + POST /llm/prepare (optional enrichment)."""
    import httpx
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    messages = parse_turns(fixture["turns"])
    report = ReplayReport(
        name=str(fixture["name"]),
        mode="http",
        turn_count=len(messages),
    )
    base_url = url.rstrip("/").removesuffix("/mcp")
    prepare_url = f"{base_url}/llm/prepare"
    normalize_url = f"{base_url}/tools/normalize"
    headers = {"Authorization": f"Bearer {token}"}

    history: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60.0) as http:
        for idx, msg in enumerate(messages, start=1):
            history.append(dict(msg))
            baseline_tokens = token_count_messages(history)

            prepared_history: list[dict[str, Any]] = []
            for item in history:
                if item.get("role") != "tool":
                    prepared_history.append(dict(item))
                    continue
                tool_name = str(item.get("tool_name") or "Shell")
                raw = message_text(item.get("content"))
                resp = await http.post(
                    normalize_url,
                    headers=headers,
                    json={"tool_name": tool_name, "output": raw},
                )
                if resp.status_code != 200:
                    report.errors.append(
                        f"turn {idx}: normalize HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    body = raw
                else:
                    data = resp.json()
                    out = data.get("output")
                    body = _body_to_content(out) if out is not None else raw
                prepared_history.append(
                    {"role": "tool", "content": body, "tool_name": tool_name}
                )

            body: dict[str, Any] = {
                "messages": prepared_history,
                "append_session": False,
                "enrich": enrich,
            }
            if fixture.get("repo"):
                body["repo"] = fixture["repo"]
            if fixture.get("github"):
                body["github"] = fixture["github"]
            if token_budget is not None:
                body["token_budget"] = token_budget

            prep = await http.post(prepare_url, headers=headers, json=body)
            if prep.status_code != 200:
                report.errors.append(
                    f"turn {idx}: prepare HTTP {prep.status_code}: {prep.text[:200]}"
                )
                memory_tokens = token_count_messages(prepared_history)
                additional: str | None = None
            else:
                pdata = prep.json()
                additional = pdata.get("additional_context")
                memory_tokens = token_count_messages(
                    pdata.get("messages") or prepared_history,
                    additional_context=additional if isinstance(additional, str) else None,
                )

            report.checkpoints.append(
                Checkpoint(
                    turn=idx,
                    baseline_tokens=baseline_tokens,
                    memory_tokens=memory_tokens,
                )
            )
            if idx == len(messages) and prep.status_code == 200:
                report.additional_context = (
                    additional if isinstance(additional, str) else None
                )

        report.baseline_final_tokens = report.checkpoints[-1].baseline_tokens
        report.memory_final_tokens = report.checkpoints[-1].memory_tokens
        report.token_reduction_pct = token_reduction_pct(
            report.baseline_final_tokens, report.memory_final_tokens
        )
        if enrich:
            report.memory_enriched_tokens = report.memory_final_tokens

    recall = fixture.get("recall")
    if isinstance(recall, dict) and recall.get("query"):
        transport = StreamableHttpTransport(url, headers=headers)
        async with Client(transport) as client:
            recalled = await client.call_tool(
                "memory_recall",
                {
                    "query": str(recall["query"]),
                    "scope": recall.get("scope"),
                    "k": int(recall.get("k", 8)),
                    "repo": fixture.get("repo"),
                    "github": fixture.get("github"),
                },
            )
            records = (recalled.data or {}).get("records") or []
            haystack = " || ".join(str(r.get("content", "")) for r in records)
            expected = [str(x) for x in recall.get("expect_any") or []]
            if expected:
                report.recall_passed = score_expect_any(haystack, expected)

    expect = fixture.get("context_expect_any")
    if isinstance(expect, list) and expect:
        haystack_parts: list[str] = []
        if report.additional_context:
            haystack_parts.append(report.additional_context)
        haystack_parts.extend(message_text(m.get("content")) for m in history)
        report.context_expect_passed = score_expect_any(
            "\n".join(haystack_parts), [str(x) for x in expect]
        )

    return report


def turn_labels_from_fixture(fixture: dict[str, Any]) -> list[str]:
    """Short labels for dashboard charts (one per replay turn)."""
    labels: list[str] = []
    for item in fixture.get("turns") or []:
        if not isinstance(item, dict):
            labels.append("turn")
            continue
        if "user" in item:
            text = str(item["user"]).strip().replace("\n", " ")
            labels.append(f"user: {text[:48]}{'…' if len(text) > 48 else ''}")
            continue
        if "assistant" in item:
            text = str(item["assistant"]).strip().replace("\n", " ")
            labels.append(f"assistant: {text[:40]}{'…' if len(text) > 40 else ''}")
            continue
        if "system" in item:
            labels.append("system")
            continue
        tool = item.get("tool")
        if isinstance(tool, dict):
            name = str(tool.get("name") or "tool")
            if "generate" in tool:
                labels.append(f"tool {name} ({tool['generate']})")
            else:
                labels.append(f"tool {name}")
            continue
        role = str(item.get("role") or "turn")
        labels.append(role)
    return labels


def report_to_dict(
    report: ReplayReport,
    fixture: dict[str, Any],
    *,
    fixture_path: str | None = None,
    agent_results: list[dict[str, Any]] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """JSON shape consumed by the comparison dashboard."""
    labels = turn_labels_from_fixture(fixture)
    return {
        "fixture": report.name,
        "fixture_path": fixture_path,
        "mode": report.mode,
        "recorded_at": recorded_at,
        "turn_count": report.turn_count,
        "turn_labels": labels,
        "baseline_final_tokens": report.baseline_final_tokens,
        "memory_final_tokens": report.memory_final_tokens,
        "token_reduction_pct": report.token_reduction_pct,
        "recall_passed": report.recall_passed,
        "context_expect_passed": report.context_expect_passed,
        "checkpoints": [
            {
                "turn": cp.turn,
                "label": labels[cp.turn - 1] if cp.turn - 1 < len(labels) else f"turn {cp.turn}",
                "baseline_tokens": cp.baseline_tokens,
                "memory_tokens": cp.memory_tokens,
                "saved_pct": token_reduction_pct(cp.baseline_tokens, cp.memory_tokens),
            }
            for cp in report.checkpoints
        ],
        "errors": report.errors,
        "agent": agent_results or None,
        "passed": _report_passed(report, agent_results),
    }


def _report_passed(
    report: ReplayReport, agent_results: list[dict[str, Any]] | None
) -> bool:
    if report.context_expect_passed is False:
        return False
    if report.recall_passed is False:
        return False
    if report.errors:
        return False
    if agent_results:
        return all(row.get("success") for row in agent_results)
    return True


def format_report_table(report: ReplayReport) -> str:
    lines = [
        f"# Conversation replay: {report.name}",
        f"mode={report.mode} turns={report.turn_count}",
        "",
        "| turn | baseline tok | memory tok | saved% |",
        "|---|---:|---:|---:|",
    ]
    for cp in report.checkpoints:
        saved = token_reduction_pct(cp.baseline_tokens, cp.memory_tokens)
        lines.append(
            f"| {cp.turn} | {cp.baseline_tokens} | {cp.memory_tokens} | {saved:.1f}% |"
        )
    lines.extend(
        [
            "",
            f"**Final:** baseline {report.baseline_final_tokens} tok → "
            f"memory {report.memory_final_tokens} tok "
            f"({report.token_reduction_pct:.1f}% reduction)",
        ]
    )
    if report.recall_passed is not None:
        mark = "PASS" if report.recall_passed else "FAIL"
        lines.append(f"**Recall probe:** {mark}")
    if report.context_expect_passed is not None:
        mark = "PASS" if report.context_expect_passed else "FAIL"
        lines.append(f"**Context expect:** {mark}")
    if report.errors:
        lines.append("")
        lines.append("**Errors:**")
        lines.extend(f"- {err}" for err in report.errors)
    return "\n".join(lines)
