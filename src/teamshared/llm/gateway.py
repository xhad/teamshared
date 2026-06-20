"""Pre-LLM pipeline: session append → compress → enrich."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from teamshared.compress.ccr_store import CcrStore, org_scope_from_id
from teamshared.compress.engine import compress_messages_with_ccr
from teamshared.compress.types import CompressStats
from teamshared.config import Settings
from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.memory.context_assembler import ContextAssembler, ContextPack
from teamshared.memory.facade import MemoryFacade
from teamshared.metrics import METRICS

log = get_logger(__name__)

_CONTEXT_HEADER = "## TeamShared context\n\n"


@dataclass
class GatewayPrepareResult:
    """Messages ready for the upstream LLM plus pipeline metadata."""

    messages: list[dict[str, Any]]
    session_id: str | None = None
    context_pack: ContextPack | None = None
    compress_stats: CompressStats = field(default_factory=CompressStats)
    compressed: bool = False
    session_appended: bool = False
    enriched: bool = False


def last_user_text(messages: list[dict[str, Any]]) -> str | None:
    """Return the last non-empty user message string."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def inject_context(messages: list[dict[str, Any]], rendered: str) -> list[dict[str, Any]]:
    """Prepend or append teamshared context pack into the system prompt."""
    if not rendered.strip():
        return messages
    block = _CONTEXT_HEADER + rendered.rstrip() + "\n"
    out = [dict(m) for m in messages]
    for i, msg in enumerate(out):
        if msg.get("role") == "system":
            existing = msg.get("content")
            if isinstance(existing, str):
                out[i] = {**msg, "content": existing.rstrip() + "\n\n" + block}
            else:
                out[i] = {**msg, "content": block}
            return out
    out.insert(0, {"role": "system", "content": block})
    return out


async def resolve_session_id(
    facade: MemoryFacade,
    principal: Principal,
    *,
    session_id: str | None,
    repo: str | None,
    github: str | None,
    topic: str,
) -> str:
    if session_id:
        return session_id
    opened = await facade.session_open(
        principal,
        topic=topic[:120],
        ttl=None,
        agent_override=None,
        repo=repo,
        github=github,
    )
    return opened["session_id"]


async def prepare_llm_messages(
    settings: Settings,
    facade: MemoryFacade,
    principal: Principal,
    messages: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    repo: str | None = None,
    github: str | None = None,
    append_session: bool = True,
    enrich: bool = True,
    ccr_store: CcrStore | None = None,
    token_budget: int | None = None,
    caller_agent: str | None = None,
) -> GatewayPrepareResult:
    """Run session append → compress incoming → enrich before an LLM call."""
    payload = deepcopy(messages)
    user_text = last_user_text(payload)
    resolved_session: str | None = session_id
    session_appended = False
    context_pack: ContextPack | None = None
    enriched = False

    if append_session and user_text and settings.llm_prepare_enabled:
        try:
            topic = user_text[:120]
            resolved_session = await resolve_session_id(
                facade,
                principal,
                session_id=resolved_session,
                repo=repo,
                github=github,
                topic=topic,
            )
            await facade.session_append(
                principal,
                session_id=resolved_session,
                role="user",
                content=user_text,
            )
            session_appended = True
        except Exception as exc:
            log.warning("gateway_session_append_failed", error=str(exc))

    compress_stats = CompressStats()
    compressed = False
    if ccr_store is not None:
        c_result = await compress_messages_with_ccr(
            settings,
            payload,
            org_scope=org_scope_from_id(principal.org_id),
            store=ccr_store,
        )
        payload = c_result.messages
        compress_stats = c_result.stats
        compressed = c_result.compressed
    else:
        from teamshared.compress.engine import compress_messages

        c_result = compress_messages(settings, payload)
        payload = c_result.messages
        compress_stats = c_result.stats
        compressed = c_result.compressed
    if compressed:
        METRICS.compress_requests.inc()
        METRICS.compress_chars_saved.inc(compress_stats.chars_saved)

    if enrich and user_text and settings.llm_prepare_enabled:
        try:
            assembler = ContextAssembler(facade)
            budget = token_budget or settings.llm_prepare_context_token_budget
            context_pack = await assembler.assemble(
                principal,
                task=user_text,
                repo=repo,
                github=github,
                token_budget=budget,
                caller_agent=caller_agent,
            )
            if context_pack.rendered.strip():
                payload = inject_context(payload, context_pack.rendered)
                enriched = True
        except Exception as exc:
            log.warning("gateway_context_enrich_failed", error=str(exc))

    return GatewayPrepareResult(
        messages=payload,
        session_id=resolved_session,
        context_pack=context_pack,
        compress_stats=compress_stats,
        compressed=compressed,
        session_appended=session_appended,
        enriched=enriched,
    )
