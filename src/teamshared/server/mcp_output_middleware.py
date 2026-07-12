"""FastMCP middleware: strip, clean, and compress tool responses."""

from __future__ import annotations

import json
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from teamshared.auth import current_principal
from teamshared.compress.ccr_store import org_scope_from_id
from teamshared.compress.factory import ccr_store_from_working
from teamshared.compress.tool_output import SKIP_TOOL_NAMES, normalize_tool_output
from teamshared.config import get_settings
from teamshared.logging import get_logger
from teamshared.metrics import METRICS
from teamshared.server.state import get_state

log = get_logger(__name__)


def _extract_payload(result: ToolResult) -> Any | None:
    if result.structured_content is not None:
        return result.structured_content
    content = result.content
    if not content:
        return None
    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    if not texts:
        return None
    raw = "\n".join(texts)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _uses_wrap_result(original: ToolResult) -> bool:
    """True when FastMCP wrapped the payload as ``{"result": ...}``."""
    if isinstance(original.meta, dict) and original.meta.get("fastmcp", {}).get("wrap_result"):
        return True
    structured = original.structured_content
    return isinstance(structured, dict) and set(structured.keys()) == {"result"}


def _structured_body(original: ToolResult, body: Any) -> dict[str, Any]:
    """Build MCP-compliant structured_content, preserving wrap-result shape."""
    if _uses_wrap_result(original):
        return {"result": body}
    if isinstance(body, dict):
        return body
    return {"output": body}


def _rebuild_result(original: ToolResult, body: Any) -> ToolResult:
    if isinstance(body, (dict, str)):
        return ToolResult(
            structured_content=_structured_body(original, body),
            meta=original.meta,
            is_error=original.is_error,
        )
    return ToolResult(
        structured_content=body,
        meta=original.meta,
        is_error=original.is_error,
    )


def _ensure_structured(result: ToolResult, payload: Any) -> ToolResult:
    """Backfill structured_content when the serializer only emitted text blocks."""
    if result.structured_content is not None:
        return result
    if isinstance(payload, (dict, str)):
        return _rebuild_result(result, payload)
    return result


class ToolOutputNormalizeMiddleware(Middleware):
    """Shrink MCP tool payloads before they reach the agent."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        if result.is_error:
            return result

        name = getattr(context.message, "name", None) or ""
        base = name.split(":")[-1] if ":" in name else name
        if base in SKIP_TOOL_NAMES:
            return result

        settings = get_settings()
        if not settings.mcp_tool_output_normalize_enabled:
            return result

        payload = _extract_payload(result)
        if payload is None:
            return result

        try:
            principal = current_principal()
            state = get_state()
            store = ccr_store_from_working(settings, state.working)
            org_scope = org_scope_from_id(principal.org_id) if principal else "org:default"
            normalized = await normalize_tool_output(
                settings,
                name,
                payload,
                org_scope=org_scope,
                store=store,
            )
        except Exception as exc:
            log.warning("mcp_tool_output_normalize_failed", tool=name, error=str(exc))
            return result

        if not normalized.compressed and not normalized.cleaned:
            return _ensure_structured(result, payload)

        if normalized.compressed:
            METRICS.compress_requests.inc()
            METRICS.compress_chars_saved.inc(normalized.chars_saved)

        rebuilt = _rebuild_result(result, normalized.body)
        return _ensure_structured(rebuilt, normalized.body)
