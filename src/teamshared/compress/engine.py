"""Compress chat message payloads before they reach an LLM."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from teamshared.compress.smart_crusher import try_compress_json_text
from teamshared.compress.types import CompressResult, CompressStats
from teamshared.config import Settings
from teamshared.logging import get_logger

log = get_logger(__name__)

# Injected recall packs must never be truncated by the compressor.
_TEAMSHARED_CONTEXT_MARKER = "## TeamShared context"


def is_teamshared_context_content(content: str) -> bool:
    """True when ``content`` is (or contains) an assembled TeamShared context pack."""
    return _TEAMSHARED_CONTEXT_MARKER in content

_LOG_ERROR_RE = re.compile(
    r"\b(error|failed|failure|exception|fatal|critical|traceback)\b",
    re.IGNORECASE,
)


def _message_content(msg: dict[str, Any]) -> str | None:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def _set_message_content(msg: dict[str, Any], text: str) -> dict[str, Any]:
    out = dict(msg)
    content = msg.get("content")
    if isinstance(content, list):
        replaced = False
        new_blocks: list[Any] = []
        for block in content:
            if not replaced and isinstance(block, dict) and (
                block.get("type") in ("text", "tool_result") or "text" in block
            ):
                nb = dict(block)
                if "text" in nb:
                    nb["text"] = text
                else:
                    nb["content"] = text
                new_blocks.append(nb)
                replaced = True
            else:
                new_blocks.append(block)
        if not replaced:
            new_blocks.append({"type": "text", "text": text})
        out["content"] = new_blocks
    else:
        out["content"] = text
    return out


def _compress_log_text(content: str, *, max_lines: int) -> tuple[str, bool]:
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content, False
    head = max(3, int(max_lines * 0.25))
    tail = max(3, int(max_lines * 0.15))
    budget = max(1, max_lines - head - tail)
    error_lines = [ln for ln in lines if _LOG_ERROR_RE.search(ln)]
    middle = lines[head : len(lines) - tail]
    picked: list[str] = []
    seen: set[str] = set()
    for ln in error_lines + middle:
        if ln in seen:
            continue
        seen.add(ln)
        picked.append(ln)
        if len(picked) >= budget:
            break
    kept = lines[:head] + picked + lines[-tail:]
    note = (
        f"[teamshared compressed log {len(lines)} → {len(kept)} lines; "
        f"use context_retrieve(ref=...) for full output]\n"
    )
    return note + "\n".join(kept), True


def compress_text(
    content: str,
    settings: Settings,
) -> tuple[str, bool, dict[str, Any] | None]:
    """Compress a single text blob according to settings."""
    min_chars = settings.compress_min_chars
    if len(content) < min_chars:
        return content, False, None

    compressed, changed, meta = try_compress_json_text(
        content, max_items=settings.compress_json_max_items
    )
    if changed:
        return compressed, True, meta

    if content.count("\n") >= 20:
        out, changed = _compress_log_text(content, max_lines=settings.compress_log_max_lines)
        if changed:
            return out, True, {"strategy": "log_lines"}

    target_chars = max(min_chars, int(len(content) * settings.compress_target_ratio))
    if len(content) <= target_chars:
        return content, False, None
    head = content[: target_chars // 2]
    tail = content[-(target_chars // 2) :]
    note = (
        f"[teamshared compressed text {len(content)} → ~{len(head) + len(tail)} chars; "
        f"use context_retrieve(ref=...) for full payload]\n"
    )
    return note + head + "\n…\n" + tail, True, {"strategy": "text_truncate"}


def compress_messages(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    refs: list[str] | None = None,
) -> CompressResult:
    """Return a copy of ``messages`` with compressible blocks shrunk in place."""
    stats = CompressStats()
    out: list[dict[str, Any]] = []
    touched = False

    for msg in messages:
        role = str(msg.get("role") or "")
        if role == "user":
            out.append(msg)
            continue

        content = _message_content(msg)
        if content is None:
            out.append(msg)
            continue

        if is_teamshared_context_content(content):
            out.append(msg)
            continue

        stats.original_chars += len(content)
        new_content, changed, _meta = compress_text(content, settings)
        stats.compressed_chars += len(new_content)

        if changed:
            touched = True
            stats.messages_touched += 1
            if refs is not None:
                # Caller stores original and attaches ref to compressed body.
                pass
            out.append(_set_message_content(msg, new_content))
        else:
            stats.compressed_chars += len(content)
            out.append(msg)

    return CompressResult(
        messages=out if touched else messages,
        stats=stats,
        compressed=touched,
    )


async def compress_messages_with_ccr(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    org_scope: str,
    store: Any,
) -> CompressResult:
    """Like ``compress_messages`` but stores originals in CCR and embeds refs."""
    stats = CompressStats()
    out: list[dict[str, Any]] = []
    touched = False

    for msg in messages:
        role = str(msg.get("role") or "")
        if role == "user":
            out.append(msg)
            continue

        content = _message_content(msg)
        if content is None:
            out.append(msg)
            continue

        if is_teamshared_context_content(content):
            out.append(msg)
            continue

        stats.original_chars += len(content)
        new_content, changed, _meta = compress_text(content, settings)

        if changed:
            ref = await store.put(org_scope, content)
            stats.refs.append(ref)
            new_content = f"{new_content.rstrip()}\nref={ref}\n"
            touched = True
            stats.messages_touched += 1
            stats.compressed_chars += len(new_content)
            out.append(_set_message_content(deepcopy(msg), new_content))
        else:
            stats.compressed_chars += len(content)
            out.append(msg)

    return CompressResult(
        messages=out if touched else messages,
        stats=stats,
        compressed=touched,
    )
