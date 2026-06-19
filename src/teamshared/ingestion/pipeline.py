"""The guarded memory write path.

``IngestionPipeline.ingest`` is the single funnel for creating durable memory.
It enforces the create permission, dedupes by content hash, blocks hard
secrets, redacts other PII, screens for prompt injection, routes risky or
review-required items to the approval queue (stored ``quarantined`` /
``pending_approval`` so they are invisible to retrieval until approved), embeds
+ stores, and audits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from teamshared.identity.rbac import Permissions
from teamshared.ingestion.approvals import ApprovalQueue
from teamshared.ingestion.injection import InjectionVerdict, screen_injection
from teamshared.ingestion.pii import PIIFinding, has_hard_secret, redact_pii, scan_pii
from teamshared.logging import get_logger
from teamshared.memory.audit import AuditLog
from teamshared.memory.autolink import GraphBackend, apply_autolink
from teamshared.memory.ontology import OntologyStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.request_context import RequestContext
from teamshared.memory.skills import OrgSkillStore
from teamshared.memory.strategic import OrgStrategicStore
from teamshared.memory.types import MemoryItemScope, MemoryKind, MemorySource, Visibility
from teamshared.memory.vectorstore import VectorStore
from teamshared.memory.work import WorkPriority, WorkStatus, WorkStore
from teamshared.metrics import METRICS

log = get_logger(__name__)


class IngestionRejected(Exception):  # noqa: N818 - idiomatic name; not an *Error
    """Raised when content must not be stored at all (e.g. a hard secret)."""


@dataclass
class IngestionResult:
    memory_id: UUID | None
    status: str               # active | pending_approval | quarantined | duplicate
    deduped_of: UUID | None = None
    pii: list[PIIFinding] = field(default_factory=list)
    injection: InjectionVerdict | None = None


@dataclass
class ProcedureIngestionResult:
    procedure: dict[str, Any]
    status: str               # active | pending_approval | quarantined
    pii: list[PIIFinding] = field(default_factory=list)
    injection: InjectionVerdict | None = None


@dataclass
class SkillIngestionResult:
    skill: dict[str, Any]
    status: str               # active | pending_approval | quarantined
    pii: list[PIIFinding] = field(default_factory=list)
    injection: InjectionVerdict | None = None


@dataclass
class StrategicIngestionResult:
    entity: dict[str, Any]
    entity_type: str
    status: str               # pending_approval | quarantined
    pii: list[PIIFinding] = field(default_factory=list)
    injection: InjectionVerdict | None = None


@dataclass
class WorkIngestionResult:
    item: dict[str, Any]
    status: str               # active | pending_approval | quarantined
    pii: list[PIIFinding] = field(default_factory=list)
    injection: InjectionVerdict | None = None


class IngestionPipeline:
    def __init__(
        self,
        vector_store: VectorStore,
        approvals: ApprovalQueue,
        audit: AuditLog,
        procedural: OrgProceduralStore,
        skills: OrgSkillStore,
        strategic: OrgStrategicStore,
        work: WorkStore,
        graph: GraphBackend | None = None,
        autolink_enabled: bool = True,
        ontology: OntologyStore | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.approvals = approvals
        self.audit = audit
        self.procedural = procedural
        self.skills = skills
        self.strategic = strategic
        self.work = work
        self.graph = graph
        self.autolink_enabled = autolink_enabled
        self.ontology = ontology

    async def _autolink_allowed_predicates(self, org_id: UUID) -> frozenset[str] | None:
        if self.ontology is None:
            return None
        link_types = await self.ontology.list_link_types(org_id)
        if not link_types:
            return None
        return frozenset(lt["name"] for lt in link_types)

    async def ingest(
        self,
        ctx: RequestContext,
        content: str,
        *,
        kind: MemoryKind = "note",
        pillar: str = "semantic",
        scope: MemoryItemScope = "org",
        scope_ref_id: UUID | None = None,
        visibility: Visibility = "private",
        subject: str | None = None,
        tags: list[str] | None = None,
        source: MemorySource = "manual",
        source_ref: dict[str, Any] | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        require_approval: bool = False,
    ) -> IngestionResult:
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_CREATE)

        # Dedup.
        dup = await self.vector_store.find_duplicate(ctx.org_id, content)
        if dup is not None:
            return IngestionResult(memory_id=dup, status="duplicate", deduped_of=dup)

        # PII / secrets.
        findings = scan_pii(content)
        if has_hard_secret(findings):
            await self.audit.record(
                agent=ctx.principal.attribution, action="memory.rejected_secret",
                org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
                resource_type="memory", request_id=ctx.request_id,
                payload={"findings": [f.kind for f in findings]},
            )
            raise IngestionRejected("content contains a hard secret and was not stored")
        safe_content = redact_pii(content) if findings else content

        # Injection screening.
        verdict = screen_injection(safe_content)

        # Decide status.
        # Connector/extraction sources and explicit flags route to review.
        needs_review = require_approval or source in {"connector", "extraction"}
        if verdict.quarantine:
            status = "quarantined"
        elif needs_review:
            status = "pending_approval"
        else:
            status = "active"

        owner_type = ctx.principal.type if ctx.principal.type in {"user", "agent"} else None
        memory_id = await self.vector_store.add(
            org_id=ctx.org_id,
            content=safe_content,
            kind=kind,
            pillar=pillar,
            scope=scope,
            scope_ref_id=scope_ref_id,
            visibility=visibility,
            subject=subject,
            tags=tags,
            source=source,
            source_ref=source_ref,
            confidence=confidence,
            importance=importance,
            owner_type=owner_type,
            owner_id=ctx.principal.id,
            creator_type=ctx.principal.type,
            creator_id=ctx.principal.id,
            status=status,
        )

        if status != "active":
            reason = "prompt_injection_suspected" if verdict.quarantine else "review_required"
            METRICS.ingestion_quarantined.inc(status=status, reason=reason)
            await self.approvals.enqueue(
                ctx.org_id, memory_id, reason=reason, requested_by=ctx.principal.id
            )

        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.create",
            org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
            resource_type="memory", target_id=str(memory_id), request_id=ctx.request_id,
            after={"status": status, "scope": scope, "visibility": visibility, "source": source},
        )
        if status == "active" and self.graph is not None and self.autolink_enabled:
            allowed = await self._autolink_allowed_predicates(ctx.org_id)
            validator = (
                self.ontology.validate_link if self.ontology is not None else None
            )
            await apply_autolink(
                self.graph,
                content=safe_content,
                subject=subject,
                tags=tags,
                org_id=str(ctx.org_id),
                agent=ctx.principal.attribution,
                allowed_predicates=allowed,
                link_validator=validator,
            )
        return IngestionResult(
            memory_id=memory_id, status=status, pii=findings, injection=verdict
        )

    async def ingest_procedure(
        self,
        ctx: RequestContext,
        *,
        name: str,
        steps_md: str,
        description: str | None = None,
        tool_recipe: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent: str,
        source: MemorySource = "agent",
    ) -> ProcedureIngestionResult:
        """Guarded write path for versioned procedural playbooks."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_CREATE)

        parts = [name, description or "", steps_md]
        if tool_recipe is not None:
            parts.append(json.dumps(tool_recipe, sort_keys=True))
        screen_text = "\n".join(parts)

        findings = scan_pii(screen_text)
        if has_hard_secret(findings):
            await self.audit.record(
                agent=ctx.principal.attribution,
                action="procedure.rejected_secret",
                org_id=ctx.org_id,
                actor_type=ctx.principal.type,
                actor_id=ctx.principal.id,
                resource_type="procedure",
                request_id=ctx.request_id,
                payload={"name": name, "findings": [f.kind for f in findings]},
            )
            raise IngestionRejected("content contains a hard secret and was not stored")

        if findings:
            safe_steps = redact_pii(steps_md)
            safe_description = redact_pii(description) if description else None
        else:
            safe_steps = steps_md
            safe_description = description

        verdict = screen_injection(screen_text)
        needs_review = source in {"connector", "extraction"}
        if verdict.quarantine:
            status = "quarantined"
        elif needs_review:
            status = "pending_approval"
        else:
            status = "active"

        row = await self.procedural.set_procedure(
            ctx.org_id,
            name,
            safe_steps,
            agent=agent,
            tool_recipe=tool_recipe,
            tags=tags,
            description=safe_description,
            status=status,
        )

        if status != "active":
            reason = "prompt_injection_suspected" if verdict.quarantine else "review_required"
            METRICS.ingestion_quarantined.inc(status=status, reason=reason)
            await self.approvals.enqueue_procedure(
                ctx.org_id,
                int(row["id"]),
                reason=reason,
                requested_by=ctx.principal.id,
            )

        await self.audit.record(
            agent=ctx.principal.attribution,
            action="procedure.create",
            org_id=ctx.org_id,
            actor_type=ctx.principal.type,
            actor_id=ctx.principal.id,
            resource_type="procedure",
            target_id=str(row["id"]),
            request_id=ctx.request_id,
            after={"name": name, "version": row["version"], "status": status, "source": source},
        )
        return ProcedureIngestionResult(
            procedure=row, status=status, pii=findings, injection=verdict
        )

    async def ingest_skill(
        self,
        ctx: RequestContext,
        *,
        name: str,
        body_md: str,
        description: str | None = None,
        tool_hints: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent: str,
        source: MemorySource = "agent",
    ) -> SkillIngestionResult:
        """Guarded write path for versioned agent skills."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_CREATE)

        parts = [name, description or "", body_md]
        if tool_hints is not None:
            parts.append(json.dumps(tool_hints, sort_keys=True))
        screen_text = "\n".join(parts)

        findings = scan_pii(screen_text)
        if has_hard_secret(findings):
            await self.audit.record(
                agent=ctx.principal.attribution,
                action="skill.rejected_secret",
                org_id=ctx.org_id,
                actor_type=ctx.principal.type,
                actor_id=ctx.principal.id,
                resource_type="skill",
                request_id=ctx.request_id,
                payload={"name": name, "findings": [f.kind for f in findings]},
            )
            raise IngestionRejected("content contains a hard secret and was not stored")

        if findings:
            safe_body = redact_pii(body_md)
            safe_description = redact_pii(description) if description else None
        else:
            safe_body = body_md
            safe_description = description

        verdict = screen_injection(screen_text)
        needs_review = source in {"connector", "extraction"}
        if verdict.quarantine:
            status = "quarantined"
        elif needs_review:
            status = "pending_approval"
        else:
            status = "active"

        row = await self.skills.set_skill(
            ctx.org_id,
            name,
            safe_body,
            agent=agent,
            tool_hints=tool_hints,
            tags=tags,
            description=safe_description,
            status=status,
        )

        if status != "active":
            reason = "prompt_injection_suspected" if verdict.quarantine else "review_required"
            METRICS.ingestion_quarantined.inc(status=status, reason=reason)
            await self.approvals.enqueue_skill(
                ctx.org_id,
                int(row["id"]),
                reason=reason,
                requested_by=ctx.principal.id,
            )

        await self.audit.record(
            agent=ctx.principal.attribution,
            action="skill.create",
            org_id=ctx.org_id,
            actor_type=ctx.principal.type,
            actor_id=ctx.principal.id,
            resource_type="skill",
            target_id=str(row["id"]),
            request_id=ctx.request_id,
            after={"name": name, "version": row["version"], "status": status, "source": source},
        )
        return SkillIngestionResult(
            skill=row, status=status, pii=findings, injection=verdict
        )

    async def ingest_strategic_statement(
        self,
        ctx: RequestContext,
        *,
        kind: str,
        content_md: str,
        agent: str,
    ) -> StrategicIngestionResult:
        return await self._ingest_strategic(
            ctx,
            entity_type="statement",
            screen_text=f"{kind}\n{content_md}",
            agent=agent,
            create=lambda status: self.strategic.set_statement(
                ctx.org_id, kind, content_md, agent=agent, status=status  # type: ignore[arg-type]
            ),
            audit_action="strategic.statement.create",
            audit_payload={"kind": kind},
        )

    async def ingest_strategic_plan(
        self,
        ctx: RequestContext,
        *,
        name: str,
        period_start: date,
        period_end: date,
        agent: str,
    ) -> StrategicIngestionResult:
        return await self._ingest_strategic(
            ctx,
            entity_type="plan",
            screen_text=f"{name}\n{period_start}\n{period_end}",
            agent=agent,
            create=lambda status: self.strategic.create_plan(
                ctx.org_id,
                name=name,
                period_start=period_start,
                period_end=period_end,
                agent=agent,
                status=status,
            ),
            audit_action="strategic.plan.create",
            audit_payload={"name": name},
        )

    async def ingest_strategic_objective(
        self,
        ctx: RequestContext,
        *,
        plan_id: UUID,
        title: str,
        description_md: str | None,
        owner_type: str | None,
        owner_id: UUID | None,
        sort_order: int,
        agent: str,
    ) -> StrategicIngestionResult:
        return await self._ingest_strategic(
            ctx,
            entity_type="objective",
            screen_text=f"{title}\n{description_md or ''}",
            agent=agent,
            create=lambda status: self.strategic.create_objective(
                ctx.org_id,
                plan_id=plan_id,
                title=title,
                description_md=description_md,
                owner_type=owner_type,
                owner_id=owner_id,
                sort_order=sort_order,
                agent=agent,
                status=status,
            ),
            audit_action="strategic.objective.create",
            audit_payload={"plan_id": str(plan_id), "title": title},
        )

    async def ingest_strategic_key_result(
        self,
        ctx: RequestContext,
        *,
        objective_id: UUID,
        title: str,
        description_md: str | None,
        metric_target: float | None,
        metric_current: float | None,
        metric_unit: str | None,
        track_status: str,
        agent: str,
    ) -> StrategicIngestionResult:
        return await self._ingest_strategic(
            ctx,
            entity_type="key_result",
            screen_text=f"{title}\n{description_md or ''}",
            agent=agent,
            create=lambda status: self.strategic.create_key_result(
                ctx.org_id,
                objective_id=objective_id,
                title=title,
                description_md=description_md,
                metric_target=metric_target,
                metric_current=metric_current,
                metric_unit=metric_unit,
                track_status=track_status,
                agent=agent,
                status=status,
            ),
            audit_action="strategic.key_result.create",
            audit_payload={"objective_id": str(objective_id), "title": title},
        )

    async def ingest_strategic_initiative(
        self,
        ctx: RequestContext,
        *,
        plan_id: UUID,
        title: str,
        description_md: str | None,
        objective_id: UUID | None,
        key_result_id: UUID | None,
        agent: str,
    ) -> StrategicIngestionResult:
        return await self._ingest_strategic(
            ctx,
            entity_type="initiative",
            screen_text=f"{title}\n{description_md or ''}",
            agent=agent,
            create=lambda status: self.strategic.create_initiative(
                ctx.org_id,
                plan_id=plan_id,
                title=title,
                description_md=description_md,
                objective_id=objective_id,
                key_result_id=key_result_id,
                agent=agent,
                status=status,
            ),
            audit_action="strategic.initiative.create",
            audit_payload={"plan_id": str(plan_id), "title": title},
        )

    async def _ingest_strategic(
        self,
        ctx: RequestContext,
        *,
        entity_type: str,
        screen_text: str,
        agent: str,
        create: Any,
        audit_action: str,
        audit_payload: dict[str, Any],
    ) -> StrategicIngestionResult:
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_CREATE)

        findings = scan_pii(screen_text)
        if has_hard_secret(findings):
            await self.audit.record(
                agent=ctx.principal.attribution,
                action=f"{audit_action}.rejected_secret",
                org_id=ctx.org_id,
                actor_type=ctx.principal.type,
                actor_id=ctx.principal.id,
                resource_type="strategic",
                request_id=ctx.request_id,
                payload={**audit_payload, "findings": [f.kind for f in findings]},
            )
            raise IngestionRejected("content contains a hard secret and was not stored")

        verdict = screen_injection(screen_text)
        status = "quarantined" if verdict.quarantine else "pending_approval"
        row = await create(status)

        reason = "prompt_injection_suspected" if verdict.quarantine else "strategic_review_required"
        METRICS.ingestion_quarantined.inc(status=status, reason=reason)
        await self.approvals.enqueue_strategic(
            ctx.org_id,
            entity_type,
            UUID(str(row["id"])),
            reason=reason,
            requested_by=ctx.principal.id,
        )

        await self.audit.record(
            agent=ctx.principal.attribution,
            action=audit_action,
            org_id=ctx.org_id,
            actor_type=ctx.principal.type,
            actor_id=ctx.principal.id,
            resource_type="strategic",
            target_id=str(row["id"]),
            request_id=ctx.request_id,
            after={**audit_payload, "status": status, "entity_type": entity_type},
        )
        return StrategicIngestionResult(
            entity=row, entity_type=entity_type, status=status,
            pii=findings, injection=verdict,
        )

    async def ingest_work_create(
        self,
        ctx: RequestContext,
        *,
        title: str,
        description_md: str | None,
        tags: list[str] | None,
        work_status: WorkStatus,
        priority: WorkPriority,
        requester_type: str | None,
        requester_id: UUID | None,
        assignee_type: str | None,
        assignee_id: UUID | None,
        initiative_id: UUID | None,
        due_at: Any,
        repo: str | None,
        github: str | None,
        agent: str,
        require_approval: bool = True,
        project_id: UUID | None = None,
        section_id: UUID | None = None,
        parent_id: UUID | None = None,
        start_at: Any = None,
        item_type: str = "task",
    ) -> WorkIngestionResult:
        await ctx.authorizer.require(ctx.principal, Permissions.WORK_WRITE)
        screen_text = f"{title}\n{description_md or ''}"
        findings = scan_pii(screen_text)
        if has_hard_secret(findings):
            await self.audit.record(
                agent=ctx.principal.attribution,
                action="work.create.rejected_secret",
                org_id=ctx.org_id,
                actor_type=ctx.principal.type,
                actor_id=ctx.principal.id,
                resource_type="work",
                request_id=ctx.request_id,
                payload={"title": title, "findings": [f.kind for f in findings]},
            )
            raise IngestionRejected("content contains a hard secret and was not stored")

        verdict = screen_injection(screen_text)
        if verdict.quarantine:
            status = "quarantined"
        elif require_approval:
            status = "pending_approval"
        else:
            status = "active"

        row = await self.work.create(
            ctx.org_id,
            title=title,
            description_md=description_md,
            tags=tags,
            work_status=work_status,
            priority=priority,
            requester_type=requester_type,  # type: ignore[arg-type]
            requester_id=requester_id,
            assignee_type=assignee_type,  # type: ignore[arg-type]
            assignee_id=assignee_id,
            initiative_id=initiative_id,
            due_at=due_at,
            repo=repo,
            github=github,
            source="agent",
            agent=agent,
            status=status,  # type: ignore[arg-type]
            parent_id=parent_id,
            start_at=start_at,
            item_type=item_type,  # type: ignore[arg-type]
        )

        if project_id is not None:
            await self.work.add_to_project(
                ctx.org_id, UUID(str(row["id"])), project_id, section_id=section_id,
            )

        if status in {"pending_approval", "quarantined"}:
            reason = "prompt_injection_suspected" if verdict.quarantine else "work_review_required"
            METRICS.ingestion_quarantined.inc(status=status, reason=reason)
            await self.approvals.enqueue_work(
                ctx.org_id,
                UUID(str(row["id"])),
                reason=reason,
                requested_by=ctx.principal.id,
            )

        await self.audit.record(
            agent=ctx.principal.attribution,
            action="work.create",
            org_id=ctx.org_id,
            actor_type=ctx.principal.type,
            actor_id=ctx.principal.id,
            resource_type="work",
            target_id=str(row["id"]),
            request_id=ctx.request_id,
            after={"title": title, "status": status},
        )
        return WorkIngestionResult(
            item=row, status=status, pii=findings, injection=verdict,
        )
