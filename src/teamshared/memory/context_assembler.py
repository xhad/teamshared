"""Context assembler -- pre-warm an agent's working memory before it reasons.

The pillars are passive stores; this module is the active step that runs
*before* a model reasons. It fans out recall across the durable pillars and the
optional graph in parallel, merges + token-budgets the result, and renders a
single sectioned, cited "context pack" the model can consume in one shot.

It deliberately builds on top of :class:`teamshared.memory.facade.MemoryFacade`
rather than the stores directly: ``facade.recall`` already runs the secure
retrieval pipeline (tenant resolution, ``memory:read`` pre-check, scope filter,
vector + keyword merge, rerank, defence-in-depth scope recheck). The assembler
never bypasses it -- it only adds parallelism across pillars, a token budget,
and a packing/format step. The pure helpers (``plan_queries``, ``pack_records``,
``render_pack``) are kept free of I/O so they are cheap to unit-test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord, MemoryScope
from teamshared.metrics import METRICS

if TYPE_CHECKING:
    from teamshared.identity.principal import Principal
    from teamshared.memory.facade import MemoryFacade

log = get_logger(__name__)

# Pillars assembled by default. ``working`` is caller-scoped (handled by recall
# when ``caller_agent`` is set); the rest are the shared-brain durable pillars.
DEFAULT_ASSEMBLE_SCOPES: tuple[MemoryScope, ...] = (
    "semantic", "episodic", "procedural", "skill", "strategic", "work", "working",
)

# Roughly 4 chars per token -- good enough to budget a pack without a tokenizer.
_CHARS_PER_TOKEN = 4
# Conservative default: ~25% of a small (8k) window.
DEFAULT_TOKEN_BUDGET = 1500
# How much of each record's content to surface in the pack.
_SNIPPET_MAX_CHARS = 240

# Render order: instructions (procedural) first, then facts, then state.
_PILLAR_ORDER: tuple[str, ...] = (
    "procedural", "skill", "semantic", "graph", "strategic", "work", "episodic", "working",
)


class ContextPack(BaseModel):
    """A single, token-budgeted, sectioned context bundle for one task."""

    task: str
    rendered: str
    tokens_used: int
    token_budget: int
    counts_by_pillar: dict[str, int] = Field(default_factory=dict)
    errors_by_pillar: dict[str, str] = Field(default_factory=dict)
    records: list[MemoryRecord] = Field(default_factory=list)


@dataclass
class QueryPlan:
    """Recall queries derived from the task plus cursor context."""

    primary: str
    entities: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (ceil of chars / 4); always at least 1."""
    if not text:
        return 1
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def plan_queries(task: str, open_files: list[str]) -> QueryPlan:
    """Build a primary recall query plus graph entities from open files.

    For a weak model this is intentionally mechanical: the task text is the
    primary query, and each open file's base name (sans extension) becomes a
    candidate graph entity for the relationship lookup.
    """
    entities: list[str] = []
    seen: set[str] = set()
    for path in open_files:
        base = path.rsplit("/", 1)[-1].strip()
        if not base:
            continue
        stem = base.rsplit(".", 1)[0] if "." in base else base
        for candidate in (base, stem):
            if candidate and candidate not in seen:
                seen.add(candidate)
                entities.append(candidate)
    return QueryPlan(primary=task.strip(), entities=entities[:5])


def _record_snippet(record: MemoryRecord) -> str:
    """One markdown bullet: truncated content plus provenance for citation."""
    content = (record.content or "").strip().replace("\n", " ")
    if len(content) > _SNIPPET_MAX_CHARS:
        content = content[: _SNIPPET_MAX_CHARS - 1].rstrip() + "\u2026"
    meta: list[str] = []
    if record.agent:
        meta.append(record.agent)
    if record.created_at is not None:
        meta.append(record.created_at.date().isoformat())
    if record.confidence is not None:
        meta.append(f"conf={record.confidence:.2f}")
    sep = " \u00b7 "
    suffix = f" ({sep.join(meta)})" if meta else ""
    return f"- {content}{suffix}"


def _section_key(record: MemoryRecord) -> str:
    return "graph" if record.id.startswith("graph:") else record.pillar


def pack_records(
    records: list[MemoryRecord], *, token_budget: int
) -> tuple[list[MemoryRecord], int]:
    """Greedily keep highest-ranked records until the token budget is hit.

    Records are assumed pre-ranked by the caller. The first record is always
    kept (even if it alone exceeds the budget) so a pack is never empty when
    input is non-empty.
    """
    kept: list[MemoryRecord] = []
    used = 0
    for record in records:
        cost = estimate_tokens(_record_snippet(record))
        if kept and used + cost > token_budget:
            break
        kept.append(record)
        used += cost
    return kept, used


def render_pack(task: str, records: list[MemoryRecord]) -> str:
    """Render kept records as a sectioned, cited markdown pack."""
    header = f"# Context for: {task}".rstrip()
    if not records:
        return f"{header}\n\nNo relevant team memory found for this task.\n"

    sections: dict[str, list[str]] = {}
    for record in records:
        sections.setdefault(_section_key(record), []).append(_record_snippet(record))

    lines: list[str] = [header, ""]
    rendered_keys: set[str] = set()
    for pillar in _PILLAR_ORDER:
        if pillar in sections:
            lines.append(f"## {pillar.capitalize()}")
            lines.extend(sections[pillar])
            lines.append("")
            rendered_keys.add(pillar)
    for pillar, items in sections.items():
        if pillar not in rendered_keys:
            lines.append(f"## {pillar.capitalize()}")
            lines.extend(items)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class ContextAssembler:
    """Fan recall out across pillars in parallel and pack the result."""

    def __init__(self, facade: MemoryFacade) -> None:
        self.facade = facade

    async def assemble(
        self,
        principal: Principal,
        *,
        task: str,
        repo: str | None = None,
        github: str | None = None,
        open_files: list[str] | None = None,
        k_per_pillar: int = 8,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        caller_agent: str | None = None,
        graph_depth: int = 2,
        graph_limit: int = 10,
    ) -> ContextPack:
        plan = plan_queries(task, open_files or [])

        recall_coro = self.facade.recall(
            principal,
            query=plan.primary,
            scopes=list(DEFAULT_ASSEMBLE_SCOPES),
            k=k_per_pillar,
            time_range=None,
            agent_filter=None,
            caller_agent=caller_agent,
            repo=repo,
            github=github,
        )
        graph_coro = self._graph_records(
            principal, plan.entities, depth=graph_depth, limit=graph_limit
        )
        recall_result, graph_records = await asyncio.gather(recall_coro, graph_coro)

        records: list[MemoryRecord] = list(recall_result.records) + graph_records
        counts = dict(recall_result.counts_by_pillar)
        errors = dict(recall_result.errors_by_pillar)
        if graph_records:
            counts["graph"] = len(graph_records)

        kept, used = pack_records(records, token_budget=token_budget)
        rendered = render_pack(task, kept)

        METRICS.context_pack_built.inc()
        METRICS.context_pack_tokens.observe(float(used))

        return ContextPack(
            task=task,
            rendered=rendered,
            tokens_used=used,
            token_budget=token_budget,
            counts_by_pillar=counts,
            errors_by_pillar=errors,
            records=kept,
        )

    async def _graph_records(
        self, principal: Principal, names: list[str], *, depth: int, limit: int
    ) -> list[MemoryRecord]:
        """Best-effort graph neighborhood for the planned entities.

        Returns an empty list when the graph is disabled or no entities were
        planned; never raises (a graph hiccup must not fail the whole pack).
        """
        if self.facade.graph is None or not names:
            return []
        out: list[MemoryRecord] = []
        seen: set[str] = set()
        for name in names:
            try:
                recs = await self.facade.graph.related(
                    name, org_id=str(principal.org_id), depth=depth, limit=limit
                )
            except Exception as exc:
                log.warning("context_graph_failed", name=name, error=str(exc))
                continue
            for rec in recs:
                if rec.id not in seen:
                    seen.add(rec.id)
                    out.append(rec)
        return out
