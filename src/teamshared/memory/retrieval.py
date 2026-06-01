"""Secure retrieval pipeline -- tenant + permission constrained, every time.

Ordering matters and is the whole point:

1. Build request context (already done by the caller).
2. Tenant resolution -- every query runs in ``db.org(principal.org_id)``.
3. AuthZ pre-check -- principal must hold ``memory:read`` or we raise before
   touching the index.
4. Scope filter -- computed from the principal's reach.
5. Vector search -- the scope filter is applied in SQL *before* the distance
   sort (in :class:`VectorStore`), so out-of-scope rows are never scored.
6. Keyword/hybrid search -- merged with vector hits.
7. Rerank by weighted score + recency.
8. Permission recheck -- defence in depth: drop any row whose scope is not in
   the allowed set, even though SQL already enforced it.
9. Package + audit the read event.

A missing org context, a missing permission, or a scope mismatch all fail
closed.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from teamshared.identity.rbac import Permissions
from teamshared.logging import get_logger
from teamshared.memory.audit import AuditLog
from teamshared.memory.request_context import RequestContext
from teamshared.memory.types import MemoryRecord, MemoryScope, RecallResult, TimeRange
from teamshared.memory.vectorstore import ScopeFilter, VectorStore
from teamshared.metrics import METRICS
from teamshared.telemetry import span

log = get_logger(__name__)

DEFAULT_SCOPE: tuple[MemoryScope, ...] = ("semantic", "episodic", "procedural")

PILLAR_WEIGHTS: dict[str, float] = {
    "semantic": 1.0,
    "episodic": 0.9,
    "procedural": 0.85,
    "working": 0.7,
}


class SecureRetrieval:
    def __init__(self, vector_store: VectorStore, audit: AuditLog) -> None:
        self.vector_store = vector_store
        self.audit = audit

    async def search(
        self,
        ctx: RequestContext,
        query: str,
        *,
        scopes: Iterable[MemoryScope] = DEFAULT_SCOPE,
        k: int = 8,
        time_range: TimeRange | None = None,
        author_agent_id: UUID | None = None,
    ) -> RecallResult:
        # (3) pre-check -- fail closed before any retrieval.
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        started = time.monotonic()

        scopes_tuple = tuple(scopes)

        def want(s: MemoryScope) -> bool:
            return s in scopes_tuple or "all" in scopes_tuple

        tr = (time_range.since, time_range.until) if time_range else None

        # (4) scope filter from the principal's reach.
        scope_filter = await ctx.accessible_scope_filter()

        records: list[MemoryRecord] = []
        counts: dict[str, int] = {}
        errors: dict[str, str] = {}

        # (5)+(6) durable semantic/episodic via vector + keyword, merged.
        if want("semantic") or want("episodic"):
            pillar = None
            if want("semantic") and not want("episodic"):
                pillar = "semantic"
            elif want("episodic") and not want("semantic"):
                pillar = "episodic"
            try:
                with span("memory.vector_search", org_id=str(ctx.org_id), request_id=ctx.request_id):
                    vec = await self.vector_store.search(
                        org_id=ctx.org_id, query=query, scope_filter=scope_filter,
                        k=k, pillar=pillar, time_range=tr, author_agent_id=author_agent_id,
                    )
                    kw = await self.vector_store.keyword_search(
                        org_id=ctx.org_id, query=query, scope_filter=scope_filter, k=k,
                        author_agent_id=author_agent_id,
                    )
                merged = _merge_by_id(vec, kw)
                counts["semantic_episodic"] = len(merged)
                records.extend(merged)
            except Exception as exc:
                log.warning("retrieval_vector_failed", error=str(exc))
                errors["semantic_episodic"] = str(exc)

        # procedural -- org-scoped FTS.
        if want("procedural"):
            try:
                proc = await self._procedural_search(ctx, query, k)
                counts["procedural"] = len(proc)
                records.extend(proc)
            except Exception as exc:
                log.warning("retrieval_procedural_failed", error=str(exc))
                errors["procedural"] = str(exc)

        # (7) rerank.
        ranked = _rerank(records, k=k)
        # (8) permission recheck -- defence in depth.
        safe = _recheck_scope(ranked, scope_filter, org_id=str(ctx.org_id))

        METRICS.retrieval_latency.observe(time.monotonic() - started)

        # (9) audit the read.
        await self.audit.record(
            agent=ctx.principal.attribution,
            action="memory.read",
            actor_type=ctx.principal.type,
            actor_id=ctx.principal.id,
            resource_type="memory",
            payload={"query": query, "returned": len(safe), "scopes": list(scopes_tuple)},
            request_id=ctx.request_id,
        )
        return RecallResult(
            query=query, records=safe, counts_by_pillar=counts, errors_by_pillar=errors
        )

    async def _procedural_search(
        self, ctx: RequestContext, query: str, k: int
    ) -> list[MemoryRecord]:
        async with ctx.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                """
                SELECT DISTINCT ON (name)
                    id, name, version, description, steps_md, tags, created_by, created_at,
                    ts_rank(
                        to_tsvector('english',
                            coalesce(name,'') || ' ' || coalesce(description,'') || ' ' || coalesce(steps_md,'')),
                        plainto_tsquery('english', %s)
                    ) AS rank
                FROM procedures
                WHERE to_tsvector('english',
                        coalesce(name,'') || ' ' || coalesce(description,'') || ' ' || coalesce(steps_md,''))
                      @@ plainto_tsquery('english', %s)
                ORDER BY name, version DESC, rank DESC
                LIMIT %s
                """,
                (query, query, k),
            )
            rows = await cur.fetchall()
        out: list[MemoryRecord] = []
        for r in rows:
            out.append(
                MemoryRecord(
                    id=str(r[0]),
                    pillar="procedural",
                    kind="procedure",
                    content=f"{r[1]} (v{r[2]}): {r[3] or (r[4] or '')[:200]}",
                    agent=r[6],
                    tags=list(r[5] or []),
                    score=float(r[8]) if r[8] is not None else None,
                    created_at=r[7],
                    org_id=ctx.org_id,
                )
            )
        return out


def _merge_by_id(primary: Sequence[MemoryRecord], extra: Sequence[MemoryRecord]) -> list[MemoryRecord]:
    seen = {r.id for r in primary}
    merged = list(primary)
    for r in extra:
        if r.id not in seen:
            merged.append(r)
            seen.add(r.id)
    return merged


def _rerank(records: list[MemoryRecord], *, k: int) -> list[MemoryRecord]:
    now = datetime.now(UTC)

    def score_of(r: MemoryRecord) -> float:
        base = r.score if r.score is not None else 0.5
        weight = PILLAR_WEIGHTS.get(r.pillar, 0.5)
        recency_bonus = 0.0
        if r.created_at and r.pillar in {"episodic", "working"}:
            age_hours = max((now - r.created_at).total_seconds() / 3600.0, 0.0)
            recency_bonus = max(0.0, 0.2 * (1.0 / (1.0 + age_hours / 24.0)))
        importance_bonus = 0.1 * (r.importance or 0.0)
        return base * weight + recency_bonus + importance_bonus

    return sorted(records, key=score_of, reverse=True)[:k]


def _recheck_scope(
    records: list[MemoryRecord], scope_filter: ScopeFilter, *, org_id: str | None = None
) -> list[MemoryRecord]:
    """Drop any record whose scope is not in the principal's allowed set.

    Procedural/working records (no first-party scope) pass through; first-party
    items must match org/user/agent/team/project/shared exactly.
    """
    allowed_teams = {str(t) for t in scope_filter.team_ids}
    allowed_projects = {str(p) for p in scope_filter.project_ids}
    safe: list[MemoryRecord] = []
    for r in records:
        if r.scope is None:
            safe.append(r)
            continue
        ref = str(r.scope_ref_id) if r.scope_ref_id else None
        ok = (
            (r.scope == "org" and scope_filter.include_org)
            or (r.visibility == "shared" and scope_filter.include_shared)
            or (r.scope == "user" and scope_filter.user_id is not None and ref == str(scope_filter.user_id))
            or (r.scope == "agent" and scope_filter.agent_id is not None and ref == str(scope_filter.agent_id))
            or (r.scope == "team" and ref in allowed_teams)
            or (r.scope == "project" and ref in allowed_projects)
        )
        if ok:
            safe.append(r)
        else:
            log.warning("retrieval_scope_recheck_dropped", memory_id=r.id, scope=r.scope)
            METRICS.cross_tenant_violation.inc(org=org_id or "unknown")
    return safe
