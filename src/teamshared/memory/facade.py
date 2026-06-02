"""Converged memory facade: one org-scoped surface behind every MCP tool.

G2 rebinds the MCP tool functions onto the org-scoped Principal + RLS stack.
To honour the "no business logic in tool functions" rule, the tools stay thin
shells that resolve the current :class:`Principal` and call one method here.
This facade builds the :class:`RequestContext`, routes durable pillars through
:class:`ProductionServices` (pgvector RLS, ingestion, retrieval), and the
volatile pillars (working memory, agent state, graph) through their org-scoped
stores.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.memory.agent_state import AgentStateStore, repo_tag
from teamshared.memory.graph import GraphStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.request_context import RequestContext
from teamshared.memory.types import MemoryKind, MemoryRecord, MemoryScope, RecallResult, TimeRange
from teamshared.memory.working import WorkingMemory
from teamshared.server.services import ProductionServices

log = get_logger(__name__)

_PILLAR_WEIGHTS: dict[str, float] = {
    "semantic": 1.0,
    "episodic": 0.9,
    "procedural": 0.85,
    "working": 0.7,
}

# Soft boost applied to durable records tagged with the caller's current repo.
# Records from other repos (or with no repo) stay visible; same-repo hits just
# rank higher. Kept modest so a strong cross-repo match can still surface.
_REPO_BOOST = 1.3


class MemoryFacade:
    def __init__(
        self,
        *,
        services: ProductionServices,
        resolver: PrincipalResolver,
        working: WorkingMemory,
        agent_state: AgentStateStore,
        procedural: OrgProceduralStore,
        graph: GraphStore | None,
    ) -> None:
        self.services = services
        self.resolver = resolver
        self.working = working
        self.agent_state = agent_state
        self.procedural = procedural
        self.graph = graph

    def _ctx(self, principal: Principal) -> RequestContext:
        return RequestContext(
            principal=principal,
            db=self.services.tenant_db,
            authorizer=self.services.authorizer(),
        )

    async def _write_principal(
        self,
        caller: Principal,
        agent_override: str | None,
        *,
        operation: str,
        request_id: str | None = None,
    ) -> Principal:
        """Resolve write attribution, honouring an ``agent=`` override when allowed.

        When the caller passes ``agent=`` distinct from their identity, record
        ``memory.agent_override`` on the audit trail (applied or rejected).
        """
        caller_label = caller.display or caller.attribution
        if not agent_override or agent_override == caller_label:
            return caller

        override = await self.resolver.for_agent(agent_override)
        applied = override.org_id == caller.org_id
        writer = override if applied else caller
        attributed = writer.display or writer.attribution

        await self.services.audit.record(
            agent=caller.attribution,
            action="memory.agent_override",
            org_id=caller.org_id,
            actor_type=caller.type,
            actor_id=caller.id,
            resource_type="attribution",
            request_id=request_id,
            payload={
                "operation": operation,
                "requested_agent": agent_override,
                "attributed_agent": attributed,
                "applied": applied,
            },
        )
        if not applied:
            log.warning(
                "agent_override_rejected",
                operation=operation,
                caller=caller_label,
                requested_agent=agent_override,
            )
        return writer

    async def _lookup_agent_id(self, org_id: UUID, name: str) -> UUID | None:
        async with self.services.tenant_db.org(org_id) as conn:
            cur = await conn.execute("SELECT id FROM agents WHERE name = %s", (name,))
            row = await cur.fetchone()
        return row[0] if row else None

    async def remember(
        self,
        principal: Principal,
        *,
        content: str,
        kind: MemoryKind,
        subject: str | None,
        tags: list[str] | None,
        agent_override: str | None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="remember",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        pillar = "episodic" if kind == "event" else "semantic"
        tag_list = _with_repo_tag(tags, repo)
        result = await self.services.ingestion().ingest(
            ctx, content, kind=kind, pillar=pillar, scope="org",
            visibility="private", subject=subject, tags=tag_list, source="agent",
        )
        return {
            "agent": writer.display or writer.attribution,
            "pillar": pillar,
            "memory_id": str(result.memory_id) if result.memory_id else None,
            "status": result.status,
        }

    async def recall(
        self,
        principal: Principal,
        *,
        query: str,
        scopes: list[MemoryScope],
        k: int,
        time_range: TimeRange | None,
        agent_filter: str | None,
        caller_agent: str | None,
        repo: str | None = None,
    ) -> RecallResult:
        ctx = self._ctx(principal)
        durable = [s for s in scopes if s in {"semantic", "episodic", "procedural", "all"}]
        author_id: UUID | None = None
        if agent_filter:
            author_id = await self._lookup_agent_id(principal.org_id, agent_filter)
            if author_id is None:
                # Asked to narrow to an agent with no writes: empty durable set.
                durable = []
        result = RecallResult(query=query, records=[], counts_by_pillar={}, errors_by_pillar={})
        if durable:
            result = await self.services.retrieval().search(
                ctx, query, scopes=durable, k=k, time_range=time_range,
                author_agent_id=author_id,
            )
        records = list(result.records)
        counts = dict(result.counts_by_pillar)
        errors = dict(result.errors_by_pillar)
        if ("working" in scopes or "all" in scopes) and caller_agent:
            try:
                working = await self.working.recent_records(principal.org_id, caller_agent, k=k)
                counts["working"] = len(working)
                records.extend(working)
            except Exception as exc:
                errors["working"] = str(exc)
        ranked = _rerank(records, k=k, repo=repo)
        return RecallResult(
            query=query, records=ranked, counts_by_pillar=counts, errors_by_pillar=errors
        )

    async def episodes_list(
        self,
        principal: Principal,
        *,
        topic: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        agent_filter: str | None,
    ) -> dict[str, Any]:
        author_id: UUID | None = None
        if agent_filter:
            author_id = await self._lookup_agent_id(principal.org_id, agent_filter)
            if author_id is None:
                return {"count": 0, "episodes": []}
        records = await self.services.vector_store.list_episodes(
            org_id=principal.org_id, topic=topic, since=since, until=until,
            limit=limit, author_agent_id=author_id,
        )
        return {"count": len(records), "episodes": [r.model_dump(mode="json") for r in records]}

    async def forget(self, principal: Principal, *, memory_id: str, reason: str) -> dict[str, Any]:
        ctx = self._ctx(principal)
        ok = await self.services.memory_service.delete(ctx, UUID(memory_id))
        log.info("memory_forget", memory_id=memory_id, reason=reason, agent=principal.attribution)
        return {"memory_id": memory_id, "deleted": ok}

    async def procedure_get(
        self, principal: Principal, *, name: str, version: int | None
    ) -> dict[str, Any] | None:
        return await self.procedural.get_procedure(principal.org_id, name, version)

    async def procedure_set(
        self,
        principal: Principal,
        *,
        name: str,
        steps_md: str,
        description: str | None,
        tool_recipe: dict[str, Any] | None,
        tags: list[str] | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="procedure_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_procedure(
            ctx,
            name=name,
            steps_md=steps_md,
            description=description,
            tool_recipe=tool_recipe,
            tags=tags,
            agent=writer.display or writer.attribution,
        )
        proc = dict(result.procedure)
        proc["status"] = result.status
        return proc

    async def procedures_list(
        self, principal: Principal, *, tag: str | None, limit: int
    ) -> dict[str, Any]:
        rows = await self.procedural.list_procedures(principal.org_id, tag=tag, limit=limit)
        return {"count": len(rows), "procedures": rows}

    async def session_open(
        self,
        principal: Principal,
        *,
        topic: str | None,
        ttl: int | None,
        agent_override: str | None,
        repo: str | None = None,
    ) -> dict[str, str]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="session_open",
            request_id=caller_ctx.request_id,
        )
        agent = writer.display or writer.attribution
        session_id = await self.working.open_session(
            principal.org_id, agent, topic=topic, ttl=ttl, repo=repo
        )
        return {"session_id": session_id, "agent": agent}

    async def session_append(
        self, principal: Principal, *, session_id: str, role: str, content: str
    ) -> dict[str, int]:
        await self._require_session_owner(principal, session_id)
        count = await self.working.append_turn(principal.org_id, session_id, role, content)
        return {"turn_count": count}

    async def session_close(
        self, principal: Principal, *, session_id: str, distill: bool
    ) -> dict[str, Any]:
        await self._require_session_owner(principal, session_id)
        return await self.working.close_session(principal.org_id, session_id, distill=distill)

    async def graph_relate(
        self,
        principal: Principal,
        *,
        subject: str,
        predicate: str,
        object_: str,
        weight: float,
        agent_override: str | None,
    ) -> dict[str, Any]:
        if self.graph is None:
            return {"ok": False, "reason": "graph_disabled"}
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="graph_relate",
            request_id=caller_ctx.request_id,
        )
        agent = writer.display or writer.attribution
        await self.graph.add_relation(
            subject, predicate, object_, org_id=str(principal.org_id), agent=agent, weight=weight
        )
        return {"ok": True, "subject": subject, "predicate": predicate, "object": object_}

    async def graph_related(
        self, principal: Principal, *, name: str, depth: int, limit: int
    ) -> dict[str, Any]:
        if self.graph is None:
            return {"records": [], "reason": "graph_disabled"}
        records = await self.graph.related(
            name, org_id=str(principal.org_id), depth=depth, limit=limit
        )
        return {"count": len(records), "records": [r.model_dump(mode="json") for r in records]}

    async def state_get(
        self, principal: Principal, *, state_id: str, repo: str, key: str
    ) -> dict[str, Any]:
        value = await self.agent_state.get(state_id, repo, key, org=str(principal.org_id))
        return {"repo": repo, "key": key, "value": value}

    async def state_set(
        self, principal: Principal, *, state_id: str, repo: str, key: str, value: dict[str, Any]
    ) -> dict[str, Any]:
        await self.agent_state.set(state_id, repo, key, value, org=str(principal.org_id))
        return {"repo": repo, "key": key, "stored": True}

    async def _require_session_owner(self, principal: Principal, session_id: str) -> None:
        meta = await self.working.get_metadata(principal.org_id, session_id)
        owner = meta.get("agent")
        caller = principal.display or principal.attribution
        if owner != caller:
            raise PermissionError(f"session {session_id} belongs to {owner!r}, not {caller!r}")


def _with_repo_tag(tags: list[str] | None, repo: str | None) -> list[str] | None:
    """Append the canonical ``repo:<slug>`` tag (deduped) when ``repo`` is set.

    An unparseable slug is ignored rather than failing the write — the memory
    is still worth storing even if it can't be repo-scoped.
    """
    tag_list = list(tags or [])
    if repo:
        try:
            rt = repo_tag(repo)
        except ValueError:
            log.warning("repo_tag_invalid", repo=repo)
        else:
            if rt not in tag_list:
                tag_list.append(rt)
    return tag_list or None


def _rerank(
    records: list[MemoryRecord], *, k: int, repo: str | None = None
) -> list[MemoryRecord]:
    target_tag: str | None = None
    if repo:
        try:
            target_tag = repo_tag(repo)
        except ValueError:
            target_tag = None

    def score_of(r: MemoryRecord) -> float:
        base = r.score if r.score is not None else 0.5
        score = base * _PILLAR_WEIGHTS.get(r.pillar, 0.5)
        if target_tag and target_tag in (r.tags or []):
            score *= _REPO_BOOST
        return score

    return sorted(records, key=score_of, reverse=True)[:k]
