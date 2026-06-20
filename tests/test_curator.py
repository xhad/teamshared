"""Curator LLM call: strict JSON parsing into {title, body_md}."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teamshared.distill import curator as curator_mod
from teamshared.distill.curator import curate
from teamshared.distill.summarizer import SummarizerError

SETTINGS = SimpleNamespace(llm_provider="openai", llm_model="gpt-4o-mini")


async def test_curate_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curator_mod, "create_chat_completion", AsyncMock(return_value={}))
    monkeypatch.setattr(
        curator_mod,
        "chat_completion_text",
        lambda _resp, *, ollama: (
            '{"title": "Infra", "body_md": "# Infra\\n\\nProd on Spark."}'
        ),
    )
    out = await curate(
        SETTINGS,  # type: ignore[arg-type]
        subject="teamshared infra",
        facts=[{"content": "prod on Spark", "kind": "fact", "confidence": 0.9,
                "created_at": "2026-05-28"}],
        episodes=[{"content": "migrated", "created_at": "2026-05-27"}],
    )
    assert out["title"] == "Infra"
    assert "Prod on Spark" in out["body_md"]


async def test_curate_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curator_mod, "create_chat_completion", AsyncMock(return_value={}))
    monkeypatch.setattr(
        curator_mod, "chat_completion_text", lambda _resp, *, ollama: "not json"
    )
    with pytest.raises(SummarizerError):
        await curate(SETTINGS, subject="x", facts=[], episodes=[])  # type: ignore[arg-type]


async def test_curate_uses_ollama_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(
        return_value={"message": {"content": '{"title": "T", "body_md": "b"}'}}
    )
    monkeypatch.setattr(curator_mod, "create_chat_completion", create)
    settings = SimpleNamespace(llm_provider="ollama", llm_model="llama3")
    out = await curate(settings, subject="x", facts=[], episodes=[])  # type: ignore[arg-type]
    assert out["body_md"] == "b"
    create.assert_awaited_once()


async def test_curate_uses_openai_path_for_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenRouter is OpenAI-compatible, so it uses the non-Ollama response path."""
    create = AsyncMock(return_value={})
    text = AsyncMock(return_value='{"title": "T", "body_md": "b"}')
    monkeypatch.setattr(curator_mod, "create_chat_completion", create)
    monkeypatch.setattr(curator_mod, "chat_completion_text", text)
    settings = SimpleNamespace(llm_provider="openrouter", llm_model="openai/gpt-4o-mini")
    out = await curate(settings, subject="x", facts=[], episodes=[])  # type: ignore[arg-type]
    assert out["body_md"] == "b"
    create.assert_awaited_once()
    text.assert_called_once()
    assert text.call_args.kwargs["ollama"] is False
