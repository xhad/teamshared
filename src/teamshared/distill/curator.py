"""LLM call that synthesizes one subject's memory into a canonical wiki article.

Mirrors :mod:`teamshared.distill.summarizer`: same OpenAI/OpenRouter/Ollama
backends, strict JSON output parsed into ``{"title", "body_md"}``. On parse
failure we raise so the worker can requeue rather than writing garbage into the
wiki.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from teamshared.compress.ccr_store import CcrStore
from teamshared.config import Settings
from teamshared.distill.prompts import CURATOR_SYSTEM, build_curator_message
from teamshared.distill.summarizer import SummarizerError
from teamshared.llm.completion import create_chat_completion
from teamshared.logging import get_logger

log = get_logger(__name__)


async def curate(
    settings: Settings,
    *,
    subject: str,
    facts: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    org_id: UUID | str | None = None,
    ccr_store: CcrStore | None = None,
) -> dict[str, Any]:
    """Call the configured LLM and return the parsed ``{title, body_md}`` page."""
    user_msg = build_curator_message(subject, facts, episodes)
    messages = [
        {"role": "system", "content": CURATOR_SYSTEM},
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
        log.error("curator_invalid_json", error=str(exc), raw=raw[:500])
        raise SummarizerError("curator LLM returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise SummarizerError("curator LLM returned a non-object JSON value")
    return data
