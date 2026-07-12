"""Strip, clean, and compress MCP tool response payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from teamshared.compress.engine import compress_text, is_teamshared_context_content
from teamshared.config import Settings
from teamshared.logging import get_logger

log = get_logger(__name__)

# Never normalize these — liveness, recursion, or already-compressed payloads.
SKIP_TOOL_NAMES = frozenset(
    {
        "health",
        "version",
        "context_compress",
        "context_retrieve",
        "context_prepare",
        "context_normalize",
        "memory_tools_catalog",
    }
)

# Strip internal/heavy keys from recall-style record dicts.
_RECORD_DROP_KEYS = frozenset(
    {
        "embedding",
        "vector",
        "raw_payload",
        "payload",
    }
)

_RECALL_TOOLS = frozenset(
    {
        "memory_recall",
        "memory_think",
        "memory_assemble_context",
        "memory_episodes_list",
        "memory_entity_view",
    }
)


@dataclass
class NormalizedToolOutput:
    """Payload returned to MCP clients and Cursor hooks."""

    body: Any
    compressed: bool = False
    chars_saved: int = 0
    ref: str | None = None
    cleaned: bool = False


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


def _clean_record(record: Any, *, max_content_chars: int) -> Any:
    if not isinstance(record, dict):
        return record
    out = {k: v for k, v in record.items() if k not in _RECORD_DROP_KEYS}
    content = out.get("content")
    if isinstance(content, str):
        out["content"] = _truncate(content, max_content_chars)
    body = out.get("body_md")
    if isinstance(body, str):
        out["body_md"] = _truncate(body, max_content_chars)
    steps = out.get("steps_md")
    if isinstance(steps, str):
        out["steps_md"] = _truncate(steps, max_content_chars)
    return out


def _clean_recall_like(payload: dict[str, Any], *, max_content_chars: int) -> dict[str, Any]:
    out = dict(payload)
    records = out.get("records")
    if isinstance(records, list):
        out["records"] = [_clean_record(r, max_content_chars=max_content_chars) for r in records]
    episodes = out.get("episodes")
    if isinstance(episodes, list):
        out["episodes"] = [_clean_record(e, max_content_chars=max_content_chars) for e in episodes]
    rendered = out.get("rendered")
    if isinstance(rendered, str) and len(rendered) > max_content_chars * 2:
        out["rendered"] = _truncate(rendered, max_content_chars * 2)
    answer = out.get("answer")
    if isinstance(answer, str) and len(answer) > max_content_chars * 3:
        out["answer"] = _truncate(answer, max_content_chars * 3)
    return out


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {k: _strip_empty(v) for k, v in value.items() if v is not None}
        return {k: v for k, v in cleaned.items() if v != {} and v != []}
    if isinstance(value, list):
        return [_strip_empty(v) for v in value if v is not None]
    return value


def clean_tool_payload(
    tool_name: str,
    payload: Any,
    *,
    settings: Settings,
) -> tuple[Any, bool]:
    """Return a smaller payload and whether anything changed."""
    if payload is None:
        return payload, False
    base_name = tool_name.split(":")[-1] if ":" in tool_name else tool_name
    changed = False
    body = payload

    if isinstance(body, dict):
        if base_name in _RECALL_TOOLS or "records" in body or "episodes" in body:
            trimmed = _clean_recall_like(
                body,
                max_content_chars=settings.mcp_tool_output_max_record_chars,
            )
            if trimmed != body:
                body = trimmed
                changed = True
        stripped = _strip_empty(body)
        if stripped != body:
            body = stripped
            changed = True
    elif isinstance(body, str) and len(body) > settings.mcp_tool_output_max_record_chars:
        body = _truncate(body, settings.mcp_tool_output_max_record_chars * 2)
        changed = True

    return body, changed


def _parse_output(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _serialize(body: Any) -> str:
    if isinstance(body, str):
        return body
    return json.dumps(body, separators=(",", ":"), default=str)


async def normalize_tool_output(
    settings: Settings,
    tool_name: str,
    output: str | dict[str, Any],
    *,
    org_scope: str,
    store: Any,
) -> NormalizedToolOutput:
    """Clean then compress a tool response for agent context."""
    if not settings.mcp_tool_output_normalize_enabled:
        body = _parse_output(output) if isinstance(output, str) else output
        return NormalizedToolOutput(body=body)

    base_name = tool_name.split(":")[-1] if ":" in tool_name else tool_name
    if base_name in SKIP_TOOL_NAMES:
        body = _parse_output(output) if isinstance(output, str) else output
        return NormalizedToolOutput(body=body)

    body = _parse_output(output) if isinstance(output, str) else output
    original_chars = len(_serialize(body))
    body, cleaned = clean_tool_payload(base_name, body, settings=settings)
    text = _serialize(body)
    clean_chars_saved = max(0, original_chars - len(text))

    if is_teamshared_context_content(text):
        return NormalizedToolOutput(
            body=body,
            cleaned=cleaned,
            chars_saved=clean_chars_saved,
        )

    new_text, compressed, _meta = compress_text(text, settings)

    if not compressed and not cleaned:
        return NormalizedToolOutput(body=body)

    # Clean-only: return trimmed payload as-is (no _teamshared noise).
    if cleaned and not compressed:
        return NormalizedToolOutput(
            body=body,
            cleaned=True,
            chars_saved=clean_chars_saved,
        )

    ref: str | None = None
    if store is not None:
        ref = await store.put(org_scope, text)

    # The compressed text *replaces* the payload — never ship both the original
    # body and a compressed preview (that would inflate, not shrink, context).
    out_body: Any
    try:
        parsed = json.loads(new_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        parsed["_teamshared"] = {
            "compressed": True,
            **({"ref": ref} if ref else {}),
        }
        out_body = parsed
        chars_saved = max(0, original_chars - len(_serialize(out_body)))
    else:
        if ref:
            new_text = f"{new_text.rstrip()}\nref={ref}\n"
        out_body = new_text
        chars_saved = max(0, original_chars - len(new_text))

    return NormalizedToolOutput(
        body=out_body,
        compressed=True,
        chars_saved=chars_saved,
        ref=ref,
        cleaned=cleaned,
    )
