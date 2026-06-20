"""Statistical JSON-array compression for tool outputs (SmartCrusher-lite)."""

from __future__ import annotations

import json
import re
from typing import Any

_ERROR_RE = re.compile(
    r"\b(error|failed|failure|exception|fatal|critical|panic|traceback|warning)\b",
    re.IGNORECASE,
)


def _item_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    try:
        return json.dumps(item, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(item)


def _score_item(item: Any) -> float:
    text = _item_text(item)
    score = 0.0
    if _ERROR_RE.search(text):
        score += 100.0
    score += min(len(text) / 200.0, 5.0)
    return score


def compress_json_array(
    items: list[Any],
    *,
    max_items: int,
    head_ratio: float = 0.30,
    tail_ratio: float = 0.15,
) -> tuple[list[Any], dict[str, Any]]:
    """Return a representative subset of a JSON array plus metadata."""
    original_count = len(items)
    if original_count <= max_items:
        return items, {"original_count": original_count, "kept_count": original_count}

    head_n = max(1, int(max_items * head_ratio))
    tail_n = max(1, int(max_items * tail_ratio))
    budget = max(1, max_items - head_n - tail_n)

    head = items[:head_n]
    tail = items[-tail_n:] if tail_n else []
    middle = items[head_n : original_count - tail_n] if tail_n else items[head_n:]

    scored = sorted(
        ((i, _score_item(item)) for i, item in enumerate(middle)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    picked_indices = sorted(idx for idx, _ in scored[:budget])
    picked = [middle[i] for i in picked_indices]

    kept = head + picked + tail
    meta = {
        "original_count": original_count,
        "kept_count": len(kept),
        "head_kept": head_n,
        "tail_kept": tail_n,
        "sampled_from_middle": len(picked),
    }
    return kept, meta


def try_compress_json_text(
    content: str,
    *,
    max_items: int,
) -> tuple[str, bool, dict[str, Any] | None]:
    """Compress JSON array payloads; pass through non-arrays unchanged."""
    stripped = content.strip()
    if not stripped.startswith("["):
        return content, False, None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return content, False, None
    if not isinstance(parsed, list) or not parsed:
        return content, False, None

    kept, meta = compress_json_array(parsed, max_items=max_items)
    if meta["kept_count"] >= meta["original_count"]:
        return content, False, None

    summary = (
        f"[teamshared compressed {meta['original_count']} → {meta['kept_count']} items; "
        f"use context_retrieve(ref=...) for full payload]\n"
    )
    compressed = summary + json.dumps(kept, ensure_ascii=False, indent=2, default=str)
    meta["strategy"] = "json_array"
    return compressed, True, meta
