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

from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.identity.principal import Principal
from teamshared.identity.rbac import Permissions
from teamshared.ingestion.pii import has_hard_secret, scan_pii
from teamshared.ingestion.pipeline import IngestionRejected
from teamshared.logging import get_logger
from teamshared.memory.agent_state import AgentStateStore, github_tag, repo_tag
from teamshared.memory.context_assembler import (
    DEFAULT_TOKEN_BUDGET,
    ContextAssembler,
    ContextPack,
)
from teamshared.memory.graph import GraphStore
from teamshared.memory.graph_pg import PostgresGraphStore
from teamshared.memory.ontology import OntologyError
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.request_context import RequestContext
from teamshared.memory.skills import OrgSkillStore
from teamshared.memory.strategic import OrgStrategicStore
from teamshared.memory.think import synthesize
from teamshared.memory.types import (
    DEFAULT_RECALL_SCOPES,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    RecallResult,
    ThinkResult,
    TimeRange,
)
from teamshared.memory.wiki import slugify
from teamshared.memory.working import WorkingMemory
from teamshared.playbook.compose import (
    expand_playbook_skills,
    parse_skill_refs,
    skill_names_from_recipe,
)
from teamshared.server.services import ProductionServices
from teamshared.workflow.definition import parse_definition

log = get_logger(__name__)

_PILLAR_WEIGHTS: dict[str, float] = {
    "semantic": 1.0,
    "strategic": 0.95,
    "work": 0.92,
    "episodic": 0.9,
    "procedural": 0.85,
    "skill": 0.88,
    "working": 0.7,
}

# Soft boost applied to durable records tagged with the caller's current repo.
# Records from other repos (or with no repo) stay visible; same-repo hits just
# rank higher. Kept modest so a strong cross-repo match can still surface.
_REPO_BOOST = 1.3
_GITHUB_BOOST = 1.3


class MemoryFacade:
    def __init__(
        self,
        *,
        services: ProductionServices,
        resolver: PrincipalResolver,
        working: WorkingMemory,
        agent_state: AgentStateStore,
        procedural: OrgProceduralStore,
        skills: OrgSkillStore,
        strategic: OrgStrategicStore,
        graph: GraphStore | PostgresGraphStore | None,
    ) -> None:
        self.services = services
        self.resolver = resolver
        self.working = working
        self.agent_state = agent_state
        self.procedural = procedural
        self.skills = skills
        self.strategic = strategic
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
        github: str | None = None,
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
        tag_list = _with_scope_tags(tags, repo=repo, github=github)
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
        github: str | None = None,
        verbose: bool = True,
        explain: bool = False,
    ) -> RecallResult:
        ctx = self._ctx(principal)
        durable = [
            s for s in scopes
            if s in {"semantic", "episodic", "procedural", "skill", "strategic", "work", "all"}
        ]
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
                author_agent_id=author_id, explain=explain,
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
        ranked = _rerank(records, k=k, repo=repo, github=github)
        if not verbose:
            ranked = [_summarize_record(r) for r in ranked]
        return RecallResult(
            query=query, records=ranked, counts_by_pillar=counts, errors_by_pillar=errors
        )

    async def think(
        self,
        principal: Principal,
        *,
        query: str,
        k: int = 12,
        repo: str | None = None,
        github: str | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        caller_agent: str | None = None,
    ) -> ThinkResult:
        """Synthesized answer with citations and gap analysis (GBrain ``think`` parity)."""
        recall = await self.recall(
            principal,
            query=query,
            scopes=list(DEFAULT_RECALL_SCOPES),
            k=k,
            time_range=None,
            agent_filter=None,
            caller_agent=caller_agent,
            repo=repo,
            github=github,
            verbose=True,
        )
        result = await synthesize(
            self.services.settings,
            query=query,
            records=recall.records,
            token_budget=token_budget,
        )
        result.counts_by_pillar = {**recall.counts_by_pillar, **result.counts_by_pillar}
        ctx = self._ctx(principal)
        await self.services.audit.record(
            agent=ctx.principal.attribution,
            action="memory.think",
            org_id=ctx.org_id,
            actor_type=ctx.principal.type,
            actor_id=ctx.principal.id,
            resource_type="memory",
            payload={
                "query": query,
                "sources_used": result.sources_used,
                "gaps": len(result.gaps),
            },
            request_id=ctx.request_id,
        )
        return result

    async def assemble_context(
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
    ) -> ContextPack:
        """Assemble a token-budgeted context pack for ``task``.

        Fans recall out across the durable pillars (via the secure
        :meth:`recall` path) and the optional graph in parallel, then packs the
        merged, ranked records into a single sectioned, cited bundle. One call
        gives an agent its whole starting context instead of issuing serial
        recall/procedure_get/graph lookups.
        """
        assembler = ContextAssembler(self)
        return await assembler.assemble(
            principal,
            task=task,
            repo=repo,
            github=github,
            open_files=open_files,
            k_per_pillar=k_per_pillar,
            token_budget=token_budget,
            caller_agent=caller_agent,
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
        self,
        principal: Principal,
        *,
        name: str,
        version: int | None,
        expand_skills: bool = False,
    ) -> dict[str, Any] | None:
        proc = await self.procedural.get_procedure(principal.org_id, name, version)
        if proc is None:
            return None
        if expand_skills:
            steps = await expand_playbook_skills(
                self.skills,
                principal.org_id,
                steps_md=proc.get("steps_md") or "",
                tool_recipe=proc.get("tool_recipe"),
            )
            proc = dict(proc)
            proc["steps_md"] = steps
            proc["content_md"] = steps
        else:
            proc = dict(proc)
            proc["content_md"] = proc.get("steps_md")
        return proc

    async def skill_resolve(
        self,
        principal: Principal,
        *,
        playbook_name: str,
        playbook_version: int | None = None,
    ) -> dict[str, Any] | None:
        proc = await self.procedural.get_procedure(
            principal.org_id, playbook_name, playbook_version
        )
        if proc is None:
            return None
        refs = parse_skill_refs(proc.get("tool_recipe"))
        resolved: list[dict[str, Any]] = []
        for ref in refs:
            skill = await self.skills.get_skill(principal.org_id, ref.name, ref.version)
            resolved.append({
                "name": ref.name,
                "version": ref.version,
                "available": skill is not None,
                "skill": skill,
            })
        return {
            "playbook": proc["name"],
            "playbook_version": proc.get("version"),
            "skills": resolved,
        }

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
        self,
        principal: Principal,
        *,
        tag: str | None,
        limit: int,
        offset: int = 0,
        include_body: bool = False,
    ) -> dict[str, Any]:
        rows = await self.procedural.list_procedures(
            principal.org_id, tag=tag, limit=limit, offset=offset,
        )
        items = [_summarize_playbook(r, include_body=include_body) for r in rows]
        next_offset = offset + len(rows) if len(rows) == limit else None
        return {"count": len(items), "procedures": items, "next_offset": next_offset}

    async def skill_get(
        self, principal: Principal, *, name: str, version: int | None
    ) -> dict[str, Any] | None:
        skill = await self.skills.get_skill(principal.org_id, name, version)
        if skill is None:
            return None
        out = dict(skill)
        out["content_md"] = out.get("body_md")
        return out

    async def skill_set(
        self,
        principal: Principal,
        *,
        name: str,
        body_md: str,
        description: str | None,
        tool_hints: dict[str, Any] | None,
        tags: list[str] | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="skill_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_skill(
            ctx,
            name=name,
            body_md=body_md,
            description=description,
            tool_hints=tool_hints,
            tags=tags,
            agent=writer.display or writer.attribution,
        )
        row = dict(result.skill)
        row["status"] = result.status
        return row

    async def skills_list(
        self,
        principal: Principal,
        *,
        tag: str | None,
        limit: int,
        offset: int = 0,
        include_body: bool = False,
    ) -> dict[str, Any]:
        rows = await self.skills.list_skills(
            principal.org_id, tag=tag, limit=limit, offset=offset,
        )
        items = [_summarize_skill(r, include_body=include_body) for r in rows]
        next_offset = offset + len(rows) if len(rows) == limit else None
        return {"count": len(items), "skills": items, "next_offset": next_offset}

    async def forget_procedure(
        self, principal: Principal, *, name: str, reason: str
    ) -> dict[str, Any]:
        count = await self.procedural.forget_by_name(principal.org_id, name)
        await self.services.audit.record(
            agent=principal.attribution,
            action="procedure.forget",
            org_id=principal.org_id,
            actor_type=principal.type,
            actor_id=principal.id,
            resource_type="procedure",
            payload={"name": name, "reason": reason, "versions": count},
        )
        return {"name": name, "deleted_versions": count, "reason": reason}

    async def forget_skill(
        self, principal: Principal, *, name: str, reason: str
    ) -> dict[str, Any]:
        count = await self.skills.forget_by_name(principal.org_id, name)
        await self.services.audit.record(
            agent=principal.attribution,
            action="skill.forget",
            org_id=principal.org_id,
            actor_type=principal.type,
            actor_id=principal.id,
            resource_type="skill",
            payload={"name": name, "reason": reason, "versions": count},
        )
        return {"name": name, "deleted_versions": count, "reason": reason}

    async def session_get(
        self, principal: Principal, *, session_id: str
    ) -> dict[str, Any]:
        await self._require_session_owner(principal, session_id)
        meta = await self.working.get_metadata(principal.org_id, session_id)
        turns = await self.working.get_turns(principal.org_id, session_id)
        return {"session_id": session_id, "metadata": meta, "turns": turns, "turn_count": len(turns)}

    async def strategic_entity_get(
        self,
        principal: Principal,
        *,
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        row = await self.strategic.get_entity(
            principal.org_id,
            entity_type,  # type: ignore[arg-type]
            UUID(entity_id),
        )
        return _serialize_strategic(row) if row else None

    async def strategic_statement_get(
        self, principal: Principal, *, kind: str
    ) -> dict[str, Any] | None:
        row = await self.strategic.get_active_statement(principal.org_id, kind)  # type: ignore[arg-type]
        return _serialize_strategic(row) if row else None

    async def strategic_statement_set(
        self,
        principal: Principal,
        *,
        kind: str,
        content_md: str,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="strategic_statement_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_strategic_statement(
            ctx, kind=kind, content_md=content_md, agent=writer.display or writer.attribution,
        )
        out = _serialize_strategic(result.entity)
        out["status"] = result.status
        return out

    async def strategic_plan_list(
        self, principal: Principal, *, active_only: bool, limit: int
    ) -> dict[str, Any]:
        rows = await self.strategic.list_plans(
            principal.org_id, active_only=active_only, limit=limit
        )
        return {"count": len(rows), "plans": [_serialize_strategic(r) for r in rows]}

    async def strategic_plan_get(
        self, principal: Principal, *, plan_id: str, include_tree: bool
    ) -> dict[str, Any] | None:
        pid = UUID(plan_id)
        if include_tree:
            tree = await self.strategic.get_plan_tree(principal.org_id, pid)
            return _serialize_strategic(tree) if tree else None
        row = await self.strategic.get_plan(principal.org_id, pid)
        return _serialize_strategic(row) if row else None

    async def strategic_plan_set(
        self,
        principal: Principal,
        *,
        name: str,
        period_start: date,
        period_end: date,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="strategic_plan_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_strategic_plan(
            ctx, name=name, period_start=period_start, period_end=period_end,
            agent=writer.display or writer.attribution,
        )
        out = _serialize_strategic(result.entity)
        out["status"] = result.status
        return out

    async def strategic_objective_set(
        self,
        principal: Principal,
        *,
        plan_id: str,
        title: str,
        description_md: str | None,
        owner_type: str | None,
        owner_id: str | None,
        sort_order: int,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="strategic_objective_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_strategic_objective(
            ctx,
            plan_id=UUID(plan_id),
            title=title,
            description_md=description_md,
            owner_type=owner_type,
            owner_id=UUID(owner_id) if owner_id else None,
            sort_order=sort_order,
            agent=writer.display or writer.attribution,
        )
        out = _serialize_strategic(result.entity)
        out["status"] = result.status
        return out

    async def strategic_key_result_set(
        self,
        principal: Principal,
        *,
        objective_id: str,
        title: str,
        description_md: str | None,
        metric_target: float | None,
        metric_current: float | None,
        metric_unit: str | None,
        track_status: str,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="strategic_key_result_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_strategic_key_result(
            ctx,
            objective_id=UUID(objective_id),
            title=title,
            description_md=description_md,
            metric_target=metric_target,
            metric_current=metric_current,
            metric_unit=metric_unit,
            track_status=track_status,
            agent=writer.display or writer.attribution,
        )
        out = _serialize_strategic(result.entity)
        out["status"] = result.status
        return out

    async def strategic_initiative_set(
        self,
        principal: Principal,
        *,
        plan_id: str,
        title: str,
        description_md: str | None,
        objective_id: str | None,
        key_result_id: str | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="strategic_initiative_set",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        result = await self.services.ingestion().ingest_strategic_initiative(
            ctx,
            plan_id=UUID(plan_id),
            title=title,
            description_md=description_md,
            objective_id=UUID(objective_id) if objective_id else None,
            key_result_id=UUID(key_result_id) if key_result_id else None,
            agent=writer.display or writer.attribution,
        )
        out = _serialize_strategic(result.entity)
        out["status"] = result.status
        return out

    async def session_open(
        self,
        principal: Principal,
        *,
        topic: str | None,
        ttl: int | None,
        agent_override: str | None,
        repo: str | None = None,
        github: str | None = None,
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
            principal.org_id, agent, topic=topic, ttl=ttl, repo=repo, github=github
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
        try:
            check = await self.services.ontology.validate_link(
                principal.org_id, predicate, subject, object_
            )
            if not check.allowed:
                return {
                    "ok": False,
                    "reason": "kind_mismatch",
                    "message": check.error or "link kind constraint failed",
                }
            if check.warning:
                log.warning(
                    "graph_relate_kind_warn",
                    predicate=predicate,
                    subject=subject,
                    object=object_,
                    warning=check.warning,
                )
        except OntologyError as exc:
            return {"ok": False, "reason": "invalid_predicate", "message": str(exc)}
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

    async def ontology_list(self, principal: Principal) -> dict[str, Any]:
        return await self.services.ontology.list_schema(principal.org_id)

    async def ontology_list_by_interface(
        self, principal: Principal, *, interface_name: str, limit: int = 50
    ) -> dict[str, Any]:
        kinds = await self.services.ontology.list_by_interface(
            principal.org_id, interface_name, limit=limit
        )
        return {"interface": interface_name, "count": len(kinds), "kinds": kinds}

    async def ontology_propose_entity(
        self,
        principal: Principal,
        *,
        kind_name: str,
        name: str,
        properties: dict[str, Any] | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="ontology_propose_entity",
            request_id=caller_ctx.request_id,
        )
        try:
            row = await self.services.ontology.propose_entity(
                principal.org_id,
                kind_name=kind_name,
                name=name,
                properties=properties,
                created_by=writer.display or writer.attribution,
            )
        except OntologyError as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": True, **row}

    async def ontology_link_type_set(
        self,
        principal: Principal,
        *,
        name: str,
        description: str | None,
        from_kinds: list[str] | None,
        to_kinds: list[str] | None,
        cardinality: str,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="ontology_link_type_set",
            request_id=caller_ctx.request_id,
        )
        _ = writer
        return await self.services.ontology.upsert_link_type(
            principal.org_id,
            name=name,
            description=description,
            from_kinds=from_kinds,
            to_kinds=to_kinds,
            cardinality=cardinality,
        )

    async def ontology_object_kind_set(
        self,
        principal: Principal,
        *,
        name: str,
        description: str | None,
        properties_schema: dict[str, Any] | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="ontology_object_kind_set",
            request_id=caller_ctx.request_id,
        )
        _ = writer
        return await self.services.ontology.upsert_object_kind(
            principal.org_id,
            name=name,
            description=description,
            properties_schema=properties_schema,
        )

    async def action_apply(
        self,
        principal: Principal,
        *,
        action_name: str,
        parameters: dict[str, Any],
        agent_override: str | None,
    ) -> dict[str, Any]:
        """Execute a governed ontology action type and log the outcome."""
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal,
            agent_override,
            operation="action_apply",
            request_id=caller_ctx.request_id,
        )
        actor = writer.display or writer.attribution
        action = await self.services.ontology.get_action_type(principal.org_id, action_name)
        if action is None:
            return {"ok": False, "reason": f"unknown action type '{action_name}'"}
        try:
            self.services.ontology.validate_action_parameters(action, parameters)
        except OntologyError as exc:
            return {"ok": False, "reason": str(exc)}

        tool = action.get("wrapper_tool") or ""
        result: dict[str, Any] | None = None
        status = "applied"
        try:
            result = await self._dispatch_action_tool(
                principal, tool=tool, parameters=parameters, agent_override=agent_override
            )
            if isinstance(result, dict) and result.get("ok") is False:
                status = "failed"
        except Exception as exc:
            status = "failed"
            result = {"error": str(exc)}
            log.warning("action_apply_failed", action=action_name, error=str(exc))

        log_id = await self.services.ontology.log_action(
            principal.org_id,
            action_type_id=UUID(str(action["id"])),
            parameters=parameters,
            result=result,
            status=status,
            actor=actor,
            request_id=caller_ctx.request_id,
        )
        return {
            "ok": status == "applied",
            "action": action_name,
            "status": status,
            "result": result,
            "log_id": log_id,
        }

    async def action_log_list(
        self, principal: Principal, *, limit: int = 20
    ) -> dict[str, Any]:
        rows = await self.services.ontology.list_action_log(principal.org_id, limit=limit)
        return {"count": len(rows), "entries": rows}

    async def _dispatch_action_tool(
        self,
        principal: Principal,
        *,
        tool: str,
        parameters: dict[str, Any],
        agent_override: str | None,
    ) -> dict[str, Any]:
        if tool == "memory_remember":
            kind_raw = str(parameters.get("kind") or "note")
            kind = cast(
                MemoryKind,
                kind_raw if kind_raw in {"fact", "preference", "event", "note"} else "note",
            )
            return await self.remember(
                principal,
                content=str(parameters["content"]),
                kind=kind,
                subject=parameters.get("subject"),
                tags=parameters.get("tags"),
                agent_override=agent_override,
                repo=parameters.get("repo"),
                github=parameters.get("github"),
            )
        if tool == "memory_graph_relate":
            return await self.graph_relate(
                principal,
                subject=str(parameters["subject"]),
                predicate=str(parameters["predicate"]),
                object_=str(parameters.get("object_entity") or parameters.get("object")),
                weight=float(parameters.get("weight") or 1.0),
                agent_override=agent_override,
            )
        if tool == "work_update":
            return await self.work_update(
                principal,
                work_id=str(parameters["work_id"]),
                title=None,
                description_md=None,
                tags=None,
                work_status=parameters.get("work_status"),
                priority=None,
                blocked_reason=None,
                assignee_type=None,
                assignee_id=None,
                assignee_agent=parameters.get("assignee_agent"),
                assignee_email=parameters.get("assignee_email"),
                initiative_id=None,
                due_at=None,
                repo=None,
                github=None,
                agent_override=agent_override,
            ) or {"ok": False, "reason": "work_not_found"}
        if tool == "memory_strategic_statement_set":
            return await self.strategic_statement_set(
                principal,
                kind=str(parameters["kind"]),
                content_md=str(parameters.get("content") or parameters.get("content_md")),
                agent_override=agent_override,
            )
        raise OntologyError(f"Unsupported wrapper tool '{tool}'")

    async def ontology_admin_view(self, principal: Principal) -> dict[str, Any]:
        org_id = principal.org_id
        schema = await self.services.ontology.list_schema(org_id)
        entities = await self.services.ontology.list_entities(org_id, limit=200)
        action_log = await self.services.ontology.list_action_log(org_id, limit=100)
        return {
            "schema": schema,
            "entities": entities,
            "action_log": action_log,
        }

    async def entity_view(self, principal: Principal, *, slug: str) -> dict[str, Any]:
        """Bundle wiki, memories, graph, and work for an entity slug."""
        org_id = principal.org_id
        entity = await self.services.ontology.get_entity_by_slug(org_id, slug)
        subject: str | None = None
        note = ""
        try:
            subjects = await self.services.vector_store.list_subjects(org_id, limit=500)
            slug_map = {slugify(s["subject"]): s["subject"] for s in subjects}
            subject = slug_map.get(slug) or (entity["name"] if entity else None)
        except Exception as exc:
            log.warning("entity_view_subjects_failed", error=str(exc))
            note = f"Subjects unavailable: {exc}"

        groups: list[tuple[str, list[MemoryRecord]]] = []
        curated: dict[str, Any] | None = None
        graph_records: list[MemoryRecord] = []
        work_items: list[dict[str, Any]] = []
        episodes: list[dict[str, Any]] = []

        if subject:
            try:
                records = await self.services.vector_store.list_by_subject(
                    org_id, subject, limit=200
                )
                by_kind: dict[str, list[MemoryRecord]] = {}
                for rec in records:
                    key = rec.kind or "note"
                    by_kind.setdefault(key, []).append(rec)
                groups = list(by_kind.items())
            except Exception as exc:
                log.warning("entity_view_memories_failed", error=str(exc))
                if not note:
                    note = f"Memories unavailable: {exc}"

        try:
            curated = await self.services.wiki.get_page(org_id, slug)
        except Exception as exc:
            log.warning("entity_view_wiki_failed", error=str(exc))

        lookup = subject or slug
        if self.graph is not None and lookup:
            try:
                graph_records = await self.graph.related(
                    lookup, org_id=str(org_id), depth=2, limit=20
                )
            except Exception as exc:
                log.warning("entity_view_graph_failed", error=str(exc))

        if subject:
            needle = subject.lower()
            try:
                rows = await self.services.work.list_items(org_id, limit=100)
                work_items = [
                    {
                        "work_id": str(w["id"]),
                        "title": w.get("title"),
                        "content": w.get("description_md") or w.get("title"),
                    }
                    for w in rows
                    if needle in (w.get("title") or "").lower()
                    or needle in (w.get("description_md") or "").lower()
                ][:20]
            except Exception as exc:
                log.warning("entity_view_work_failed", error=str(exc))

            try:
                eps = await self.services.vector_store.list_episodes(org_id=org_id, limit=30)
                episodes = [
                    {
                        "content": e.content or "",
                        "agent": e.agent,
                        "created_at": e.created_at,
                    }
                    for e in eps
                    if needle in (e.content or "").lower()
                ][:15]
            except Exception as exc:
                log.warning("entity_view_episodes_failed", error=str(exc))

        if not subject and not entity and not curated:
            note = note or "Entity not found."

        skills, playbooks = await self.related_skills_playbooks(
            org_id, slug=slug, subject=subject
        )

        return {
            "slug": slug,
            "subject": subject,
            "entity": entity,
            "note": note,
            "wiki": {"curated": curated},
            "groups": [
                (kind, [r.model_dump(mode="json") for r in recs])
                for kind, recs in groups
            ],
            "graph_records": [r.model_dump(mode="json") for r in graph_records],
            "work_items": work_items,
            "episodes": episodes,
            "skills": skills,
            "playbooks": playbooks,
        }

    async def related_skills_playbooks(
        self,
        org_id: UUID,
        *,
        slug: str,
        subject: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Lexical match of skills/playbooks to an entity slug or wiki subject."""
        needles: set[str] = {slug.lower()}
        slug_words = slug.replace("-", " ").strip()
        if slug_words:
            needles.add(slug_words)
        if subject:
            needles.add(subject.lower())

        skills_out: list[dict[str, Any]] = []
        query = subject or slug_words or slug
        try:
            for rec in await self.skills.search_skills(org_id, query, limit=8):
                meta = rec.metadata or {}
                skills_out.append(
                    {
                        "name": str(meta.get("name") or ""),
                        "version": meta.get("version"),
                        "description": (rec.content or "")[:160],
                    }
                )
        except Exception as exc:
            log.warning("related_skills_failed", error=str(exc))

        playbooks_out: list[dict[str, Any]] = []
        try:
            rows = await self.procedural.list_procedures(org_id, limit=200)
            for row in rows:
                recipe = row.get("tool_recipe") or {}
                recipe_skills = (
                    recipe.get("skills") if isinstance(recipe, dict) else None
                ) or []
                blob = " ".join(
                    str(row.get(k) or "") for k in ("name", "description", "steps_md")
                ).lower()
                blob += " " + " ".join(str(s) for s in recipe_skills).lower()
                if any(n in blob for n in needles):
                    playbooks_out.append(
                        {
                            "name": row["name"],
                            "version": row.get("version"),
                            "description": row.get("description") or "",
                            "skills": list(recipe_skills),
                        }
                    )
                if len(playbooks_out) >= 8:
                    break
        except Exception as exc:
            log.warning("related_playbooks_failed", error=str(exc))

        return skills_out[:8], playbooks_out[:8]

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

    async def work_list(
        self,
        principal: Principal,
        *,
        work_status: str | None,
        assignee: str | None,
        mine: bool,
        initiative_id: str | None,
        exclude_closed: bool,
        sort: str,
        sort_dir: str,
        limit: int,
        project_id: str | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_READ)
        assignee_type: str | None = None
        assignee_id: UUID | None = None
        if mine:
            assignee_type = principal.type
            assignee_id = principal.id
        elif assignee:
            agent_id = await self.services.work.resolve_agent_id(principal.org_id, assignee)
            if agent_id is not None:
                assignee_type, assignee_id = "agent", agent_id
            else:
                user_id = await self.services.work.resolve_user_id_by_email(
                    principal.org_id, assignee,
                )
                if user_id is not None:
                    assignee_type, assignee_id = "user", user_id
        init_uuid = UUID(initiative_id) if initiative_id else None
        rows = await self.services.work.list_items(
            principal.org_id,
            work_status=work_status,  # type: ignore[arg-type]
            assignee_type=assignee_type,  # type: ignore[arg-type]
            assignee_id=assignee_id,
            initiative_id=init_uuid,
            exclude_closed=exclude_closed,
            sort=sort,  # type: ignore[arg-type]
            sort_dir=sort_dir,  # type: ignore[arg-type]
            limit=limit,
            project_id=UUID(project_id) if project_id else None,
            offset=offset,
        )
        next_offset = offset + len(rows) if len(rows) == limit else None
        return {
            "count": len(rows),
            "items": [_serialize_work(r) for r in rows],
            "next_offset": next_offset,
        }

    async def work_get(self, principal: Principal, *, work_id: str) -> dict[str, Any] | None:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_READ)
        row = await self.services.work.get(principal.org_id, UUID(work_id))
        return _serialize_work(row) if row else None

    async def work_create(
        self,
        principal: Principal,
        *,
        title: str,
        description_md: str | None,
        tags: list[str] | None,
        work_status: str,
        priority: str,
        assignee_type: str | None,
        assignee_id: str | None,
        assignee_agent: str | None,
        assignee_email: str | None,
        initiative_id: str | None,
        due_at: datetime | None,
        repo: str | None,
        github: str | None,
        agent_override: str | None,
        project_id: str | None = None,
        section_id: str | None = None,
        parent_id: str | None = None,
        start_at: datetime | None = None,
        item_type: str = "task",
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="work_create", request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        resolved_assignee_type, resolved_assignee_id = await self._resolve_assignee(
            principal.org_id,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            assignee_agent=assignee_agent,
            assignee_email=assignee_email,
        )
        requester_type = writer.type if writer.type in {"user", "agent"} else None
        requester_id = writer.id if requester_type else None
        init_uuid = UUID(initiative_id) if initiative_id else None
        # Work creation is direct for everyone — humans and agents alike. New
        # tasks land active rather than queuing for approval; the approval queue
        # is reserved for memory/strategic writes, not the task backlog.
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        row = await self.services.work.create(
            principal.org_id,
            title=title,
            description_md=description_md,
            tags=tags,
            work_status=work_status,  # type: ignore[arg-type]
            priority=priority,  # type: ignore[arg-type]
            requester_type=requester_type,  # type: ignore[arg-type]
            requester_id=requester_id,
            assignee_type=resolved_assignee_type,  # type: ignore[arg-type]
            assignee_id=resolved_assignee_id,
            initiative_id=init_uuid,
            due_at=due_at,
            repo=repo,
            github=github,
            source="agent" if writer.type == "agent" else "human",
            agent=writer.display or writer.attribution,
            status="active",
            parent_id=UUID(parent_id) if parent_id else None,
            start_at=start_at,
            item_type=item_type,  # type: ignore[arg-type]
        )
        if project_id:
            await self.services.work.add_to_project(
                principal.org_id,
                UUID(str(row["id"])),
                UUID(project_id),
                section_id=UUID(section_id) if section_id else None,
            )
        await self.services.audit.record(
            agent=writer.attribution,
            action="work.create",
            org_id=principal.org_id,
            actor_type=writer.type,
            actor_id=writer.id,
            resource_type="work",
            target_id=str(row["id"]),
            request_id=ctx.request_id,
            after={"title": title, "status": "active"},
        )
        if resolved_assignee_type == "agent" and resolved_assignee_id:
            try:
                await self.services.agent_run_service().maybe_autorun_on_assign(
                    ctx,
                    work_id=UUID(str(row["id"])),
                    agent_id=resolved_assignee_id,
                )
            except Exception as exc:
                log.warning(
                    "work_create_autorun_failed",
                    work_id=str(row["id"]), error=str(exc),
                )
        out = _serialize_work(row)
        out["approval_status"] = "active"
        return out

    async def work_update(
        self,
        principal: Principal,
        *,
        work_id: str,
        title: str | None,
        description_md: str | None,
        tags: list[str] | None,
        work_status: str | None,
        priority: str | None,
        blocked_reason: str | None,
        assignee_type: str | None,
        assignee_id: str | None,
        assignee_agent: str | None,
        assignee_email: str | None,
        initiative_id: str | None,
        due_at: datetime | None,
        repo: str | None,
        github: str | None,
        agent_override: str | None,
        parent_id: str | None = None,
    ) -> dict[str, Any] | None:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="work_update", request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if description_md is not None:
            fields["description_md"] = description_md
        if tags is not None:
            fields["tags"] = tags
        if work_status is not None:
            fields["work_status"] = work_status
        if priority is not None:
            fields["priority"] = priority
        if blocked_reason is not None:
            fields["blocked_reason"] = blocked_reason
        if initiative_id is not None:
            fields["initiative_id"] = UUID(initiative_id) if initiative_id else None
        if parent_id is not None:
            fields["parent_id"] = UUID(parent_id) if parent_id else None
        if due_at is not None:
            fields["due_at"] = due_at
        if repo is not None:
            fields["repo"] = repo
        if github is not None:
            fields["github"] = github
        if any(x is not None for x in (assignee_type, assignee_id, assignee_agent, assignee_email)):
            atype, aid = await self._resolve_assignee(
                principal.org_id,
                assignee_type=assignee_type,
                assignee_id=assignee_id,
                assignee_agent=assignee_agent,
                assignee_email=assignee_email,
            )
            fields["assignee_type"] = atype
            fields["assignee_id"] = aid
        terminal = work_status in {"done", "cancelled"}
        if terminal:
            non_status = {k: v for k, v in fields.items() if k != "work_status"}
            if non_status:
                await self.services.work.update(
                    principal.org_id, UUID(work_id), fields=non_status,
                )
            return await self.work_close(
                principal,
                work_id=work_id,
                work_status=work_status or "done",
                agent_override=agent_override,
            )
        row = await self.services.work.update(
            principal.org_id, UUID(work_id), fields=fields,
        )
        if row is None:
            return None
        await self.services.audit.record(
            agent=writer.attribution,
            action="work.update",
            org_id=principal.org_id,
            actor_type=writer.type,
            actor_id=writer.id,
            resource_type="work",
            target_id=work_id,
            request_id=ctx.request_id,
            after=fields,
        )
        if fields.get("assignee_type") == "agent" and fields.get("assignee_id"):
            try:
                await self.services.agent_run_service().maybe_autorun_on_assign(
                    ctx, work_id=UUID(work_id), agent_id=fields["assignee_id"],
                )
            except Exception as exc:
                log.warning(
                    "work_assign_autorun_failed",
                    work_id=work_id, error=str(exc),
                )
        return _serialize_work(row)

    async def work_close(
        self,
        principal: Principal,
        *,
        work_id: str,
        work_status: str,
        agent_override: str | None,
    ) -> dict[str, Any] | None:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="work_close", request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        row = await self.services.work.close(
            principal.org_id,
            UUID(work_id),
            work_status=work_status,  # type: ignore[arg-type]
        )
        if row is None:
            return None
        await self.services.work.enrich_labels(principal.org_id, [row])
        await self.services.audit.record(
            agent=writer.attribution,
            action="work.close",
            org_id=principal.org_id,
            actor_type=writer.type,
            actor_id=writer.id,
            resource_type="work",
            target_id=work_id,
            request_id=ctx.request_id,
            after={"work_status": work_status},
        )
        await self._emit_work_close_episode(ctx, row, work_status)
        return _serialize_work(row)

    async def work_comment_add(
        self,
        principal: Principal,
        *,
        work_id: str,
        body: str,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="work_comment_add",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        item = await self.services.work.get(principal.org_id, UUID(work_id))
        if item is None:
            raise ValueError("work item not found")
        body_md = body.strip()
        if not body_md:
            raise ValueError("comment body is required")
        findings = scan_pii(body_md)
        if has_hard_secret(findings):
            raise IngestionRejected("comment contains a hard secret and was not stored")
        author_type = writer.type if writer.type in {"user", "agent"} else "agent"
        row = await self.services.work.add_comment(
            principal.org_id,
            UUID(work_id),
            author_type=author_type,  # type: ignore[arg-type]
            author_id=writer.id,
            body_md=body_md,
        )
        await self.services.audit.record(
            agent=writer.attribution,
            action="work.comment",
            org_id=principal.org_id,
            actor_type=writer.type,
            actor_id=writer.id,
            resource_type="work",
            target_id=work_id,
            request_id=ctx.request_id,
        )
        return _serialize_work(row)

    async def work_comment_list(
        self,
        principal: Principal,
        *,
        work_id: str,
        limit: int,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_READ)
        rows = await self.services.work.list_comments(
            principal.org_id, UUID(work_id), limit=limit,
        )
        return {
            "count": len(rows),
            "comments": [_serialize_work(r) for r in rows],
        }

    # -- agent runs -------------------------------------------------------

    async def agent_run_create(
        self,
        principal: Principal,
        *,
        work_id: str,
        agent: str,
        playbook_name: str | None = None,
        playbook_version: int | None = None,
        skill_name: str | None = None,
        skill_version: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        agent_id = await self.services.work.resolve_agent_id(principal.org_id, agent)
        if agent_id is None:
            raise ValueError(f"No active agent named {agent!r} in this org.")
        effective_playbook = playbook_name
        effective_version = playbook_version
        if skill_name and not playbook_name:
            skill = await self.skills.get_skill(
                principal.org_id, skill_name, skill_version
            )
            if skill is None:
                raise ValueError(
                    f"Skill {skill_name!r} is unavailable (missing or soft-deleted). "
                    "or quarantined)."
                )
            effective_playbook = f"__skill__:{skill_name}"
            effective_version = skill.get("version")
        run = await self.services.agent_run_service().assign_and_run(
            ctx,
            work_id=UUID(work_id),
            agent_id=agent_id,
            playbook_name=effective_playbook,
            playbook_version=effective_version,
            model=model,
        )
        return cast("dict[str, Any]", _serialize_deep(run))

    async def agent_run_list(
        self, principal: Principal, *, status: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        rows = await self.services.agent_run_service().list_runs(
            ctx, status=status, limit=limit,  # type: ignore[arg-type]
        )
        return {"count": len(rows), "runs": [_serialize_deep(r) for r in rows]}

    async def agent_run_get(
        self, principal: Principal, *, run_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        run = await self.services.agent_run_service().get_run(ctx, UUID(run_id))
        return cast("dict[str, Any]", _serialize_deep(run))

    async def agent_run_cancel(
        self, principal: Principal, *, run_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        run = await self.services.agent_run_service().cancel(ctx, UUID(run_id))
        return cast("dict[str, Any]", _serialize_deep(run))

    async def agent_run_retry(
        self, principal: Principal, *, run_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        run = await self.services.agent_run_service().retry(ctx, UUID(run_id))
        return cast("dict[str, Any]", _serialize_deep(run))

    # -- workflows (procedural loops) -------------------------------------

    async def workflow_define(
        self,
        principal: Principal,
        *,
        name: str,
        stages: list[dict[str, Any]],
        loop: dict[str, Any] | None,
        description: str | None,
        steps_md: str | None,
        tags: list[str] | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        tool_recipe: dict[str, Any] = {"stages": stages}
        if loop is not None:
            tool_recipe["loop"] = loop
        # Validate the stage graph before persisting (raises on a bad graph).
        parse_definition(tool_recipe)
        body = steps_md or _render_workflow_steps_md(name, stages, loop)
        return await self.procedure_set(
            principal,
            name=name,
            steps_md=body,
            description=description or f"Workflow definition: {name}",
            tool_recipe=tool_recipe,
            tags=sorted({*(tags or []), "workflow"}),
            agent_override=agent_override,
        )

    async def workflow_start(
        self,
        principal: Principal,
        *,
        workflow_name: str,
        version: int | None,
        work_ids: list[str] | None,
        selector: dict[str, Any] | None,
        max_iterations: int | None,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        run = await self.services.workflow_orchestrator().start(
            ctx,
            workflow_name=workflow_name,
            version=version,
            work_ids=[UUID(w) for w in work_ids] if work_ids else None,
            selector=selector,
            max_iterations=max_iterations,
        )
        return cast("dict[str, Any]", _serialize_deep(run))

    async def workflow_advance(
        self, principal: Principal, *, step_id: str, decision: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        run = await self.services.workflow_orchestrator().advance(
            ctx, step_id=UUID(step_id), decision=decision,
        )
        return cast("dict[str, Any]", _serialize_deep(run))

    async def workflow_cancel(
        self, principal: Principal, *, run_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        run = await self.services.workflow_orchestrator().cancel(
            ctx, run_id=UUID(run_id),
        )
        return cast("dict[str, Any]", _serialize_deep(run))

    async def workflow_list(
        self, principal: Principal, *, status: str | None, limit: int
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORKFLOW_READ)
        rows = await self.services.workflow_runs.list_runs(
            principal.org_id, status=status, limit=limit,  # type: ignore[arg-type]
        )
        return {"count": len(rows), "runs": [_serialize_deep(r) for r in rows]}

    async def workflow_status(
        self, principal: Principal, *, run_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORKFLOW_READ)
        run = await self.services.workflow_runs.get_run(principal.org_id, UUID(run_id))
        if run is None:
            return {}
        steps = await self.services.workflow_runs.list_steps_for_run(
            principal.org_id, UUID(run_id),
        )
        out = cast("dict[str, Any]", _serialize_deep(run))
        out["steps"] = [_serialize_deep(s) for s in steps]
        return out

    # -- projects ---------------------------------------------------------

    async def project_create(
        self,
        principal: Principal,
        *,
        name: str,
        description_md: str | None,
        team_id: str | None,
        default_view: str,
        color: str | None,
        owner_email: str | None,
        initiative_id: str | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="project_create",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        ctx.request_id = caller_ctx.request_id
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_WRITE)
        owner_id: UUID | None = None
        if owner_email:
            owner_id = await self.services.work.resolve_user_id_by_email(
                principal.org_id, owner_email,
            )
        row = await self.services.projects.create(
            principal.org_id,
            name=name,
            description_md=description_md,
            team_id=UUID(team_id) if team_id else None,
            default_view=default_view,  # type: ignore[arg-type]
            color=color,
            owner_id=owner_id,
            initiative_id=UUID(initiative_id) if initiative_id else None,
            created_by=writer.display or writer.attribution,
        )
        await self.services.audit.record(
            agent=writer.attribution,
            action="project.create",
            org_id=principal.org_id,
            actor_type=writer.type,
            actor_id=writer.id,
            resource_type="project",
            target_id=str(row["id"]),
            request_id=ctx.request_id,
            after={"name": name},
        )
        return _serialize_work(row)

    async def project_list(
        self,
        principal: Principal,
        *,
        team_id: str | None,
        initiative_id: str | None,
        include_archived: bool,
        limit: int,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_READ)
        rows = await self.services.projects.list_projects(
            principal.org_id,
            team_id=UUID(team_id) if team_id else None,
            initiative_id=UUID(initiative_id) if initiative_id else None,
            include_archived=include_archived,
            limit=limit,
        )
        return {"count": len(rows), "projects": [_serialize_work(r) for r in rows]}

    async def project_get(
        self, principal: Principal, *, project_id: str, include_items: bool
    ) -> dict[str, Any] | None:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_READ)
        pid = UUID(project_id)
        row = await self.services.projects.get(principal.org_id, pid)
        if row is None:
            return None
        out = _serialize_work(row)
        out["sections"] = [
            _serialize_work(s)
            for s in await self.services.projects.list_sections(principal.org_id, pid)
        ]
        status = await self.services.projects.latest_status(principal.org_id, pid)
        out["latest_status"] = _serialize_work(status) if status else None
        if include_items:
            items = await self.services.work.list_project_items(principal.org_id, pid)
            out["items"] = [_serialize_work(i) for i in items]
        return out

    async def project_update(
        self,
        principal: Principal,
        *,
        project_id: str,
        fields: dict[str, Any],
        agent_override: str | None,
    ) -> dict[str, Any] | None:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_WRITE)
        row = await self.services.projects.update(
            principal.org_id, UUID(project_id), fields=fields,
        )
        return _serialize_work(row) if row else None

    async def project_archive(
        self, principal: Principal, *, project_id: str, archived: bool
    ) -> dict[str, Any] | None:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_WRITE)
        row = await self.services.projects.archive(
            principal.org_id, UUID(project_id), archived=archived,
        )
        return _serialize_work(row) if row else None

    async def project_section_add(
        self, principal: Principal, *, project_id: str, name: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_WRITE)
        row = await self.services.projects.add_section(
            principal.org_id, UUID(project_id), name=name,
        )
        return _serialize_work(row)

    async def project_section_list(
        self, principal: Principal, *, project_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_READ)
        rows = await self.services.projects.list_sections(
            principal.org_id, UUID(project_id),
        )
        return {"count": len(rows), "sections": [_serialize_work(r) for r in rows]}

    async def project_status_post(
        self,
        principal: Principal,
        *,
        project_id: str,
        state: str,
        body_md: str | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        caller_ctx = self._ctx(principal)
        writer = await self._write_principal(
            principal, agent_override, operation="project_status_post",
            request_id=caller_ctx.request_id,
        )
        ctx = self._ctx(writer)
        await ctx.authorizer.require(ctx.principal, Permissions.PROJECT_WRITE)
        author_type = writer.type if writer.type in {"user", "agent"} else "agent"
        row = await self.services.projects.post_status(
            principal.org_id,
            UUID(project_id),
            state=state,  # type: ignore[arg-type]
            body_md=body_md,
            author_type=author_type,  # type: ignore[arg-type]
            author_id=writer.id,
        )
        return _serialize_work(row)

    # -- task membership, hierarchy, dependencies, followers --------------

    async def work_add_to_project(
        self,
        principal: Principal,
        *,
        work_id: str,
        project_id: str,
        section_id: str | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        row = await self.services.work.add_to_project(
            principal.org_id,
            UUID(work_id),
            UUID(project_id),
            section_id=UUID(section_id) if section_id else None,
        )
        return _serialize_work(row)

    async def work_remove_from_project(
        self, principal: Principal, *, work_id: str, project_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        await self.services.work.remove_from_project(
            principal.org_id, UUID(work_id), UUID(project_id),
        )
        return {"work_id": work_id, "project_id": project_id, "removed": True}

    async def work_move(
        self,
        principal: Principal,
        *,
        work_id: str,
        project_id: str,
        section_id: str | None,
        sort_order: float,
        agent_override: str | None,
    ) -> dict[str, Any] | None:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        row = await self.services.work.move(
            principal.org_id,
            UUID(work_id),
            UUID(project_id),
            section_id=UUID(section_id) if section_id else None,
            sort_order=sort_order,
        )
        return _serialize_work(row) if row else None

    async def work_subtasks_list(
        self, principal: Principal, *, work_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_READ)
        rows = await self.services.work.list_subtasks(principal.org_id, UUID(work_id))
        return {"count": len(rows), "subtasks": [_serialize_work(r) for r in rows]}

    async def work_dependency_add(
        self,
        principal: Principal,
        *,
        blocker_id: str,
        blocked_id: str,
        agent_override: str | None,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        row = await self.services.work.add_dependency(
            principal.org_id, blocker_id=UUID(blocker_id), blocked_id=UUID(blocked_id),
        )
        return _serialize_work(row)

    async def work_dependency_remove(
        self, principal: Principal, *, blocker_id: str, blocked_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        await self.services.work.remove_dependency(
            principal.org_id, blocker_id=UUID(blocker_id), blocked_id=UUID(blocked_id),
        )
        return {"blocker_id": blocker_id, "blocked_id": blocked_id, "removed": True}

    async def work_dependencies_list(
        self, principal: Principal, *, work_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_READ)
        return await self.services.work.list_dependencies(principal.org_id, UUID(work_id))

    async def work_follower_add(
        self,
        principal: Principal,
        *,
        work_id: str,
        follower_agent: str | None,
        follower_email: str | None,
        agent_override: str | None,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        ftype, fid = await self._resolve_assignee(
            principal.org_id,
            assignee_type=None,
            assignee_id=None,
            assignee_agent=follower_agent,
            assignee_email=follower_email,
        )
        if ftype is None or fid is None:
            raise ValueError("could not resolve follower")
        row = await self.services.work.add_follower(
            principal.org_id, UUID(work_id), follower_type=ftype, follower_id=fid,  # type: ignore[arg-type]
        )
        return _serialize_work(row)

    async def work_follower_remove(
        self,
        principal: Principal,
        *,
        work_id: str,
        follower_agent: str | None,
        follower_email: str | None,
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        ftype, fid = await self._resolve_assignee(
            principal.org_id,
            assignee_type=None,
            assignee_id=None,
            assignee_agent=follower_agent,
            assignee_email=follower_email,
        )
        if ftype is None or fid is None:
            raise ValueError("could not resolve follower")
        await self.services.work.remove_follower(
            principal.org_id, UUID(work_id), follower_type=ftype, follower_id=fid,  # type: ignore[arg-type]
        )
        return {"work_id": work_id, "removed": True}

    async def work_followers_list(
        self, principal: Principal, *, work_id: str
    ) -> dict[str, Any]:
        ctx = self._ctx(principal)
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_READ)
        rows = await self.services.work.list_followers(principal.org_id, UUID(work_id))
        return {"count": len(rows), "followers": [_serialize_work(r) for r in rows]}

    async def _emit_work_close_episode(
        self,
        ctx: RequestContext,
        row: dict[str, Any],
        work_status: str,
    ) -> None:
        assignee = row.get("assignee_label")
        if not assignee and row.get("assignee_type") and row.get("assignee_id"):
            assignee = f"{row['assignee_type']}:{row['assignee_id']}"
        parts = [f"Work item closed ({work_status}): {row.get('title')}"]
        if assignee:
            parts.append(f"assignee={assignee}")
        if row.get("initiative_title"):
            parts.append(f"initiative={row['initiative_title']}")
        if row.get("blocked_reason"):
            parts.append(f"blocked_reason={row['blocked_reason']}")
        tags = ["work", f"work:{row['id']}"]
        if row.get("repo"):
            tags.append(repo_tag(row["repo"]))
        if row.get("github"):
            tags.append(github_tag(row["github"]))
        try:
            await self.services.ingestion().ingest(
                ctx,
                " — ".join(parts),
                kind="event",
                pillar="episodic",
                subject=str(row.get("title") or "work"),
                tags=tags,
                source="manual",
            )
        except Exception as exc:
            log.warning("work_close_episode_failed", work_id=str(row.get("id")), error=str(exc))

    async def _resolve_assignee(
        self,
        org_id: UUID,
        *,
        assignee_type: str | None,
        assignee_id: str | None,
        assignee_agent: str | None,
        assignee_email: str | None,
    ) -> tuple[str | None, UUID | None]:
        if assignee_agent:
            aid = await self.services.work.resolve_agent_id(org_id, assignee_agent)
            return ("agent", aid) if aid else (None, None)
        if assignee_email:
            uid = await self.services.work.resolve_user_id_by_email(org_id, assignee_email)
            return ("user", uid) if uid else (None, None)
        if assignee_type and assignee_id:
            return assignee_type, UUID(assignee_id)
        if assignee_type and not assignee_id:
            return assignee_type, None
        return None, None

    async def _require_session_owner(self, principal: Principal, session_id: str) -> None:
        meta = await self.working.get_metadata(principal.org_id, session_id)
        owner = meta.get("agent")
        caller = principal.display or principal.attribution
        if owner != caller:
            raise PermissionError(f"session {session_id} belongs to {owner!r}, not {caller!r}")


def _serialize_work(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    out: dict[str, Any] = {}
    for key, val in value.items():
        out[key] = _serialize_value(val)
    return out


def _render_workflow_steps_md(
    name: str, stages: list[dict[str, Any]], loop: dict[str, Any] | None
) -> str:
    """Render a readable playbook body from a workflow's stage graph.

    Procedures require a non-empty ``steps_md``; this gives humans (and agents
    reading the playbook) a plain-language view of the same graph stored in
    ``tool_recipe``.
    """
    lines = [f"# Workflow: {name}", ""]
    for i, stage in enumerate(stages, start=1):
        owner = stage.get("owner", "agent")
        bits = [f"**{stage.get('id')}** ({owner}"]
        if stage.get("playbook"):
            bits.append(f", playbook `{stage['playbook']}`")
        if stage.get("skill"):
            bits.append(f", skill `{stage['skill']}`")
        if stage.get("agent"):
            bits.append(f", agent `{stage['agent']}`")
        bits.append(")")
        routing = []
        for key in ("on_done", "on_approve", "on_reject"):
            if stage.get(key):
                routing.append(f"{key} -> {stage[key]}")
        suffix = f" — {'; '.join(routing)}" if routing else ""
        lines.append(f"{i}. {''.join(bits)}{suffix}")
    if loop:
        lines.append("")
        lines.append(
            f"Loop: until {loop.get('until', 'all_terminal')}, "
            f"max {loop.get('max_iterations', 10)} iterations."
        )
    return "\n".join(lines)


def _serialize_strategic(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    out: dict[str, Any] = {}
    for key, val in value.items():
        if isinstance(val, dict):
            out[key] = _serialize_strategic(val)
        elif isinstance(val, list):
            out[key] = [
                _serialize_strategic(v) if isinstance(v, dict) else _serialize_value(v) for v in val
            ]
        else:
            out[key] = _serialize_value(val)
    return out


def _serialize_value(val: Any) -> Any:
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def _serialize_deep(val: Any) -> Any:
    """Recursively JSON-normalize dicts/lists (UUIDs, datetimes -> strings)."""
    if isinstance(val, dict):
        return {k: _serialize_deep(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_serialize_deep(v) for v in val]
    return _serialize_value(val)


def _with_scope_tags(
    tags: list[str] | None,
    *,
    repo: str | None = None,
    github: str | None = None,
) -> list[str] | None:
    """Append canonical ``repo:`` / ``github:`` tags (deduped) when scope is set.

    Unparseable values are ignored rather than failing the write.
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
    if github:
        try:
            gt = github_tag(github)
        except ValueError:
            log.warning("github_tag_invalid", github=github)
        else:
            if gt not in tag_list:
                tag_list.append(gt)
    return tag_list or None


def _with_repo_tag(tags: list[str] | None, repo: str | None) -> list[str] | None:
    """Backward-compatible wrapper for repo-only tagging."""
    return _with_scope_tags(tags, repo=repo)


def _rerank(
    records: list[MemoryRecord],
    *,
    k: int,
    repo: str | None = None,
    github: str | None = None,
) -> list[MemoryRecord]:
    repo_target: str | None = None
    github_target: str | None = None
    if repo:
        try:
            repo_target = repo_tag(repo)
        except ValueError:
            repo_target = None
    if github:
        try:
            github_target = github_tag(github)
        except ValueError:
            github_target = None

    def score_of(r: MemoryRecord) -> float:
        base = r.score if r.score is not None else 0.5
        score = base * _PILLAR_WEIGHTS.get(r.pillar, 0.5)
        record_tags = r.tags or []
        if repo_target and repo_target in record_tags:
            score *= _REPO_BOOST
        if github_target and github_target in record_tags:
            score *= _GITHUB_BOOST
        return score

    return sorted(records, key=score_of, reverse=True)[:k]


def _summarize_record(record: MemoryRecord) -> MemoryRecord:
    snippet = (record.content or "")[:200]
    return record.model_copy(update={"content": snippet, "metadata": {}})


def _summarize_playbook(row: dict[str, Any], *, include_body: bool) -> dict[str, Any]:
    out = dict(row)
    tool_recipe = out.get("tool_recipe")
    skill_names = skill_names_from_recipe(tool_recipe)
    if not include_body:
        out.pop("steps_md", None)
        if tool_recipe is not None:
            loop = (tool_recipe or {}).get("loop")
            out["tool_recipe"] = {
                "skills": skill_names,
                **({"loop": loop} if loop else {}),
            }
    out["skill_names"] = skill_names
    out["content_md"] = row.get("steps_md") if include_body else (row.get("description") or "")
    return out


def _summarize_skill(row: dict[str, Any], *, include_body: bool) -> dict[str, Any]:
    out = dict(row)
    if not include_body:
        out.pop("body_md", None)
    out["content_md"] = row.get("body_md") if include_body else (row.get("description") or "")
    return out
