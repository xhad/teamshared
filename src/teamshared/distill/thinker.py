"""LLM synthesis for ``memory_think`` — turns recall hits into a cited answer."""

from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from teamshared.config import Settings
from teamshared.distill.prompts import THINKER_SYSTEM, build_thinker_message
from teamshared.distill.summarizer import SummarizerError, build_chat_client
from teamshared.logging import get_logger

log = get_logger(__name__)


async def think_compose(
    settings: Settings,
    *,
    query: str,
    sources: list[dict[str, str]],
    gaps: list[dict[str, str]],
) -> dict[str, Any]:
    """Call the configured LLM and return parsed synthesis JSON."""
    if settings.llm_provider == "openrouter" and not settings.openrouter_api_key:
        raise SummarizerError("OpenRouter API key not configured")
    user_msg = build_thinker_message(query, sources, gaps)
    if settings.llm_provider == "ollama":
        raw = await _call_ollama(settings, user_msg)
    else:
        raw = await _call_openai(settings, user_msg)
    return _parse_json(raw)


async def _call_openai(settings: Settings, user_msg: str) -> str:
    client = build_chat_client(settings)
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": THINKER_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise SummarizerError(f"LLM call failed: {exc}") from exc
    return resp.choices[0].message.content or "{}"


async def _call_ollama(settings: Settings, user_msg: str) -> str:
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120) as client:
        resp = await client.post(
            "/api/chat",
            json={
                "model": settings.llm_model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
                "messages": [
                    {"role": "system", "content": THINKER_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
            },
        )
        resp.raise_for_status()
        body = resp.json()
    return body.get("message", {}).get("content") or "{}"


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("thinker_invalid_json", error=str(exc), raw=raw[:500])
        raise SummarizerError("LLM returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise SummarizerError("LLM returned non-object JSON")
    return data
