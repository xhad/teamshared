"""LLM call that turns a transcript into structured durable memories.

Supports OpenAI, OpenRouter, and Ollama backends. OpenRouter speaks the OpenAI
Chat Completions API, so it shares the OpenAI code path via a custom base URL +
key. The output is parsed as strict JSON; on parse error we log + skip rather
than poisoning the memory store with garbage.

When compression thresholds apply (see ``compress_min_chars``), long non-user
message blocks are compressed before the LLM call via :mod:`teamshared.llm.completion`.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from teamshared.compress.ccr_store import CcrStore
from teamshared.config import Settings
from teamshared.distill.prompts import SUMMARIZER_SYSTEM, build_user_message
from teamshared.llm.completion import create_chat_completion
from teamshared.logging import get_logger

log = get_logger(__name__)


class SummarizerError(RuntimeError):
    """Raised when the LLM returned a response we couldn't parse."""


async def summarize(
    settings: Settings,
    *,
    agent: str,
    topic: str | None,
    transcript: list[dict[str, str]],
    org_id: UUID | str | None = None,
    ccr_store: CcrStore | None = None,
) -> dict[str, Any]:
    """Call the configured LLM and return the parsed distillation payload."""
    user_msg = build_user_message(agent, topic, transcript)
    messages = [
        {"role": "system", "content": SUMMARIZER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    resp = await create_chat_completion(
        settings,
        messages=messages,
        org_id=org_id,
        ccr_store=ccr_store,
        temperature=0.1,
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
        log.error("summarizer_invalid_json", error=str(exc), raw=raw[:500])
        raise SummarizerError("LLM returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise SummarizerError("LLM returned a non-object JSON value")
    return data
