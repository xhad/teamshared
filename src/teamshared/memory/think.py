"""Synthesis + gap analysis for ``memory_think`` (GBrain ``think`` parity)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from teamshared.config import Settings
from teamshared.distill.summarizer import SummarizerError
from teamshared.distill.thinker import think_compose
from teamshared.logging import get_logger
from teamshared.memory.context_assembler import DEFAULT_TOKEN_BUDGET, pack_records
from teamshared.memory.types import (
    MemoryRecord,
    ThinkCitation,
    ThinkGap,
    ThinkResult,
)

log = get_logger(__name__)

_STALE_DAYS = 42
_SNIPPET_CHARS = 240
_ENTITY_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")


def detect_gaps(
    query: str,
    records: list[MemoryRecord],
    *,
    stale_days: int = _STALE_DAYS,
) -> list[ThinkGap]:
    """Rule-based gap detection before LLM synthesis."""
    gaps: list[ThinkGap] = []
    now = datetime.now(UTC)

    if not records:
        gaps.append(
            ThinkGap(
                kind="missing",
                claim=f"No team memory matches: {query}",
                detail="The brain has nothing retrieved for this query.",
            )
        )
        return gaps

    dated = [r for r in records if r.created_at is not None]
    if dated:
        newest = max(dated, key=lambda r: r.created_at)  # type: ignore[arg-type]
        assert newest.created_at is not None
        age = now - newest.created_at
        if age > timedelta(days=stale_days):
            gaps.append(
                ThinkGap(
                    kind="stale",
                    claim=f"Newest relevant memory is {age.days} days old",
                    detail=(
                        f"Last update {newest.created_at.date().isoformat()}; "
                        "recent context may live outside the brain."
                    ),
                    memory_ids=[newest.id],
                )
            )

    entities = _extract_query_entities(query)
    if entities:
        covered = {
            (r.subject or "").lower()
            for r in records
            if r.subject
        }
        covered.update(
            tok.lower()
            for r in records
            for tok in (r.content or "").split()
            if tok[:1].isupper()
        )
        missing_entities = [e for e in entities if e.lower() not in covered]
        if missing_entities:
            gaps.append(
                ThinkGap(
                    kind="missing",
                    claim=f"No memory found for: {', '.join(missing_entities)}",
                    detail="Named entities in the query have thin or no coverage.",
                )
            )

    low_conf = [r for r in records if r.confidence is not None and r.confidence < 0.5]
    if low_conf:
        gaps.append(
            ThinkGap(
                kind="low_confidence",
                claim=f"{len(low_conf)} retrieved source(s) have confidence below 0.5",
                detail="Treat these claims as weak until corroborated.",
                memory_ids=[r.id for r in low_conf[:5]],
            )
        )

    subjects: dict[str, list[MemoryRecord]] = {}
    for r in records:
        if r.subject:
            subjects.setdefault(r.subject.lower(), []).append(r)
    for subj, group in subjects.items():
        if len(group) < 2:
            continue
        unique_contents = {(_normalize(r.content)[:80]) for r in group}
        if len(unique_contents) >= 2:
            gaps.append(
                ThinkGap(
                    kind="contradicts",
                    claim=f"Conflicting takes on subject '{subj}'",
                    detail="Multiple retrieved memories disagree; verify before acting.",
                    memory_ids=[r.id for r in group[:5]],
                )
            )

    return gaps


def _extract_query_entities(query: str) -> list[str]:
    """Capitalized phrases likely naming people, companies, or projects."""
    found = _ENTITY_RE.findall(query)
    stop = {"The", "What", "Who", "When", "Where", "How", "Why", "Before", "After"}
    return [e for e in found if e not in stop]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _records_to_sources(records: list[MemoryRecord]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in records:
        content = (r.content or "").strip().replace("\n", " ")
        if len(content) > _SNIPPET_CHARS:
            content = content[: _SNIPPET_CHARS - 1].rstrip() + "\u2026"
        out.append({
            "id": r.id,
            "pillar": r.pillar,
            "agent": r.agent or "",
            "date": r.created_at.date().isoformat() if r.created_at else "",
            "content": content,
        })
    return out


def _fallback_answer(query: str, records: list[MemoryRecord], gaps: list[ThinkGap]) -> str:
    """Deterministic answer when LLM is unavailable."""
    if not records:
        return f"I could not find team memory relevant to: **{query}**."
    lines = ["## Answer (retrieval-only fallback)\n", f"Query: {query}\n"]
    for i, r in enumerate(records[:8], 1):
        snippet = (r.content or "")[:200].replace("\n", " ")
        lines.append(f"{i}. [{r.pillar}] {snippet} [{i}]")
    if gaps:
        lines.append("\n### Gaps\n")
        for g in gaps:
            lines.append(f"- **{g.kind}**: {g.claim}")
    return "\n".join(lines)


async def synthesize(
    settings: Settings,
    *,
    query: str,
    records: list[MemoryRecord],
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> ThinkResult:
    """Run gap detection then LLM synthesis over packed recall records."""
    kept, _ = pack_records(records, token_budget=token_budget)
    gaps = detect_gaps(query, kept)
    gap_dicts = [{"kind": g.kind, "claim": g.claim} for g in gaps]
    sources = _records_to_sources(kept)

    citations: list[ThinkCitation] = []
    answer_md: str

    try:
        payload = await think_compose(
            settings, query=query, sources=sources, gaps=gap_dicts
        )
        answer_md = str(payload.get("answer_md") or "").strip()
        raw_cites = payload.get("citations") or []
        id_by_index = {i + 1: s["id"] for i, s in enumerate(sources)}
        for cite in raw_cites:
            if not isinstance(cite, dict):
                continue
            idx = cite.get("index")
            mid = cite.get("memory_id") or (id_by_index.get(idx) if idx else None)
            if not mid:
                continue
            src = next((s for s in sources if s["id"] == mid), None)
            citations.append(
                ThinkCitation(
                    memory_id=str(mid),
                    pillar=src["pillar"] if src else "semantic",
                    snippet=str(cite.get("claim") or (src or {}).get("content", ""))[:240],
                    agent=src.get("agent") if src else None,
                )
            )
    except (SummarizerError, OSError, RuntimeError) as exc:
        log.warning("think_llm_failed", error=str(exc))
        answer_md = _fallback_answer(query, kept, gaps)

    if not answer_md:
        answer_md = _fallback_answer(query, kept, gaps)

    if gaps and "## Gaps" not in answer_md and "### Gaps" not in answer_md:
        gap_lines = "\n".join(f"- **{g.kind}**: {g.claim}" for g in gaps)
        answer_md = f"{answer_md.rstrip()}\n\n### Heads up\n{gap_lines}\n"

    counts: dict[str, int] = {}
    for r in kept:
        counts[r.pillar] = counts.get(r.pillar, 0) + 1

    return ThinkResult(
        query=query,
        answer_md=answer_md,
        citations=citations,
        gaps=gaps,
        sources_used=len(kept),
        counts_by_pillar=counts,
    )
