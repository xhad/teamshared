"""OpenAI-compatible chat client factory."""

from __future__ import annotations

from openai import AsyncOpenAI

from teamshared.config import Settings


def build_chat_client(settings: Settings) -> AsyncOpenAI:
    """Build an OpenAI-compatible chat client for the configured provider.

    OpenRouter implements the OpenAI Chat Completions API, so it reuses the
    same SDK with a custom base URL and key. Plain ``openai`` relies on the SDK
    defaults (``OPENAI_API_KEY`` from the environment).
    """
    if settings.llm_provider == "openrouter":
        return AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
    return AsyncOpenAI()
