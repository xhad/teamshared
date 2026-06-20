"""Central LLM chat completion path — always compresses prompts before send."""

from __future__ import annotations

from typing import Any

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from teamshared.compress.ccr_store import CcrStore, org_scope_from_id
from teamshared.compress.engine import compress_messages_with_ccr
from teamshared.config import Settings
from teamshared.llm.client import build_chat_client
from teamshared.logging import get_logger
from teamshared.metrics import METRICS

log = get_logger(__name__)


async def create_chat_completion(
    settings: Settings,
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    org_id: Any = None,
    ccr_store: CcrStore | None = None,
    **kwargs: Any,
) -> ChatCompletion | dict[str, Any]:
    """OpenAI-compatible chat completion with mandatory pre-send compression."""
    model = model or settings.llm_model
    payload = messages

    if ccr_store is not None:
        result = await compress_messages_with_ccr(
            settings,
            messages,
            org_scope=org_scope_from_id(org_id),
            store=ccr_store,
        )
        payload = result.messages
        if result.compressed:
            METRICS.compress_requests.inc()
            METRICS.compress_chars_saved.inc(result.stats.chars_saved)
            log.debug(
                "llm_prompt_compressed",
                chars_saved=result.stats.chars_saved,
                messages_touched=result.stats.messages_touched,
            )
    else:
        from teamshared.compress.engine import compress_messages

        result = compress_messages(settings, messages)
        payload = result.messages
        if result.compressed:
            METRICS.compress_requests.inc()
            METRICS.compress_chars_saved.inc(result.stats.chars_saved)

    if settings.llm_provider == "ollama":
        return await _ollama_completion(settings, payload, model=model, **kwargs)
    return await _openai_completion(settings, payload, model=model, **kwargs)


async def _openai_completion(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    model: str,
    **kwargs: Any,
) -> ChatCompletion:
    client = build_chat_client(settings)
    return await client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        **kwargs,
    )


async def _ollama_completion(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    model: str,
    **kwargs: Any,
) -> dict[str, Any]:
    temperature = kwargs.pop("temperature", 0.2)
    response_format = kwargs.pop("response_format", None)
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": {"temperature": temperature},
    }
    if response_format and response_format.get("type") == "json_object":
        body["format"] = "json"
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120) as client:
        resp = await client.post("/api/chat", json=body)
        resp.raise_for_status()
        return resp.json()
