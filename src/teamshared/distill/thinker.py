"""LLM synthesis for ``memory_think`` (GBrain ``think`` parity)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from teamshared.compress.ccr_store import CcrStore
from teamshared.config import Settings
from teamshared.distill.prompts import THINKER_SYSTEM, build_thinker_message
from teamshared.distill.summarizer import SummarizerError
from teamshared.llm.completion import create_chat_completion
from teamshared.logging import get_logger

log = get_logger(__name__)


async def think_compose(
    settings: Settings,
    *,
    query: str,
    sources: list[dict[str, str]],
    gaps: list[dict[str, str]],
    org_id: UUID | str | None = None,
    ccr_store: CcrStore | None = None,
) -> dict[str, Any]:
    """Call the configured LLM and return parsed synthesis JSON."""
    if settings.llm_provider == "openrouter" and not settings.openrouter_api_key:
        raise SummarizerError("OpenRouter API key not configured")
    user_msg = build_thinker_message(query, sources, gaps)
    messages = [
        {"role": "system", "content": THINKER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    resp = await create_chat_completion(
        settings,
        messages=messages,
        org_id=org_id,
        ccr_store=ccr_store,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    if settings.llm_provider == "ollama":
        raw = str(resp.get("message", {}).get("content") or "{}")
    else:
        raw = resp.choices[0].message.content or "{}"
    return _parse_json(raw)


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("thinker_invalid_json", error=str(exc), raw=raw[:500])
        raise SummarizerError("LLM returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise SummarizerError("LLM returned a non-object JSON value")
    return data
