"""LLM call that synthesizes one subject's memory into a canonical wiki article.

Mirrors :mod:`teamshared.distill.summarizer`: same OpenAI/OpenRouter/Ollama
backends, strict JSON output parsed into ``{"title", "body_md"}``. On parse
failure we raise so the worker can requeue rather than writing garbage into the
wiki.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from teamshared.config import Settings
from teamshared.distill.prompts import CURATOR_SYSTEM, build_curator_message
from teamshared.distill.summarizer import SummarizerError, build_chat_client
from teamshared.logging import get_logger

log = get_logger(__name__)


async def curate(
    settings: Settings,
    *,
    subject: str,
    facts: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call the configured LLM and return the parsed ``{title, body_md}`` page."""
    user_msg = build_curator_message(subject, facts, episodes)
    if settings.llm_provider == "ollama":
        raw = await _call_ollama(settings, user_msg)
    else:
        raw = await _call_openai(settings, user_msg)
    return _parse_json(raw)


async def _call_openai(settings: Settings, user_msg: str) -> str:
    client = build_chat_client(settings)
    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": CURATOR_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
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
                    {"role": "system", "content": CURATOR_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
            },
        )
        resp.raise_for_status()
        body = resp.json()
    content: str = body.get("message", {}).get("content") or "{}"
    return content


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("curator_invalid_json", error=str(exc), raw=raw[:500])
        raise SummarizerError("curator LLM returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise SummarizerError("curator LLM returned a non-object JSON value")
    return data
