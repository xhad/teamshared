"""LLM call that turns a transcript into structured durable memories.

Supports OpenAI and Ollama backends. The output is parsed as strict JSON; on
parse error we log + skip rather than poisoning the memory store with garbage.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from teamshared.config import Settings
from teamshared.distill.prompts import SUMMARIZER_SYSTEM, build_user_message
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
) -> dict[str, Any]:
    """Call the configured LLM and return the parsed distillation payload."""
    user_msg = build_user_message(agent, topic, transcript)
    if settings.llm_provider == "openai":
        raw = await _call_openai(settings, user_msg)
    else:
        raw = await _call_ollama(settings, user_msg)
    return _parse_json(raw)


async def _call_openai(settings: Settings, user_msg: str) -> str:
    client = AsyncOpenAI()
    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SUMMARIZER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
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
                "options": {"temperature": 0.1},
                "messages": [
                    {"role": "system", "content": SUMMARIZER_SYSTEM},
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
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("summarizer_invalid_json", error=str(exc), raw=raw[:500])
        raise SummarizerError("LLM returned invalid JSON") from exc
