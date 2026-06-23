"""LLM provider plumbing: config + OpenAI-compatible client routing.

OpenRouter speaks the OpenAI Chat Completions API, so teamshared routes it
through the same SDK with a custom base URL + key. These tests pin that the
client is built for the right provider and that the distiller/curator route
non-Ollama providers through the OpenAI code path.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teamshared.config import Settings, get_settings
from teamshared.distill import summarizer as summarizer_mod
from teamshared.distill.summarizer import summarize
from teamshared.llm.client import build_chat_client


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("TEAMSHARED_") or key == "OPENROUTER_API_KEY":
            monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


def test_openrouter_settings_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert s.openrouter_api_key is None


def test_openrouter_api_key_reads_unprefixed_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("TEAMSHARED_LLM_PROVIDER", "openrouter")
    s = Settings(_env_file=None)
    assert s.llm_provider == "openrouter"
    assert s.openrouter_api_key == "sk-or-test"


def test_build_chat_client_openrouter_uses_custom_base_url() -> None:
    settings = SimpleNamespace(
        llm_provider="openrouter",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_api_key="sk-or-test",
    )
    client = build_chat_client(settings)  # type: ignore[arg-type]
    assert str(client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    assert client.api_key == "sk-or-test"


def test_build_chat_client_openai_uses_sdk_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    settings = SimpleNamespace(llm_provider="openai")
    client = build_chat_client(settings)  # type: ignore[arg-type]
    assert "openai.com" in str(client.base_url)
    assert client.api_key == "sk-openai-test"


async def test_summarize_routes_openrouter_through_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value={})
    monkeypatch.setattr(summarizer_mod, "create_chat_completion", create)
    monkeypatch.setattr(
        summarizer_mod,
        "chat_completion_text",
        lambda _resp, *, ollama: '{"facts": []}',
    )
    settings = SimpleNamespace(llm_provider="openrouter", llm_model="openai/gpt-4o-mini")
    out = await summarize(settings, agent="cursor", topic="t", transcript=[])  # type: ignore[arg-type]
    assert out == {"facts": []}
    create.assert_awaited_once()
