"""Shared context-prepare logic for MCP tools and HTTP handlers."""

from __future__ import annotations

from typing import Any

from teamshared.compress.factory import ccr_store_from_working
from teamshared.config import Settings
from teamshared.identity.principal import Principal
from teamshared.llm.gateway import prepare_llm_messages
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.working import WorkingMemory

_CONTEXT_HEADER = "## TeamShared context\n\n"


def prompt_to_messages(prompt: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt}]


def additional_context_from_pack(rendered: str | None) -> str | None:
    if not rendered or not rendered.strip():
        return None
    return _CONTEXT_HEADER + rendered.rstrip() + "\n"


async def run_context_prepare(
    settings: Settings,
    facade: MemoryFacade,
    principal: Principal,
    working: WorkingMemory,
    *,
    messages: list[dict[str, Any]] | None = None,
    prompt: str | None = None,
    session_id: str | None = None,
    repo: str | None = None,
    github: str | None = None,
    append_session: bool = True,
    enrich: bool = True,
    token_budget: int | None = None,
) -> dict[str, Any]:
    """Session append → compress incoming → enrich; returns JSON-serializable result."""
    if not settings.llm_prepare_enabled:
        raise ValueError("llm_prepare_disabled")

    payload = list(messages or [])
    if not payload and isinstance(prompt, str) and prompt.strip():
        payload = prompt_to_messages(prompt.strip())
    if not payload:
        raise ValueError("messages or prompt required")

    store = ccr_store_from_working(settings, working)
    prepared = await prepare_llm_messages(
        settings,
        facade,
        principal,
        payload,
        session_id=session_id,
        repo=repo,
        github=github,
        append_session=append_session,
        enrich=enrich,
        ccr_store=store,
        token_budget=token_budget,
        caller_agent=principal.display if principal.type == "agent" else None,
    )

    rendered = prepared.context_pack.rendered if prepared.context_pack else None
    return {
        "messages": prepared.messages,
        "session_id": prepared.session_id,
        "additional_context": additional_context_from_pack(rendered),
        "stats": {
            "session_appended": prepared.session_appended,
            "enriched": prepared.enriched,
            "compressed": prepared.compressed,
            "chars_saved": prepared.compress_stats.chars_saved,
            "original_chars": prepared.compress_stats.original_chars,
            "compressed_chars": prepared.compress_stats.compressed_chars,
        },
    }
