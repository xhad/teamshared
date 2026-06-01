"""The guarded memory write path.

``IngestionPipeline.ingest`` is the single funnel for creating durable memory.
It enforces the create permission, dedupes by content hash, blocks hard
secrets, redacts other PII, screens for prompt injection, routes risky or
review-required items to the approval queue (stored ``quarantined`` /
``pending_approval`` so they are invisible to retrieval until approved), embeds
+ stores, and audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from teamshared.identity.rbac import Authorizer, Permissions
from teamshared.ingestion.approvals import ApprovalQueue
from teamshared.ingestion.injection import InjectionVerdict, screen_injection
from teamshared.ingestion.pii import PIIFinding, has_hard_secret, redact_pii, scan_pii
from teamshared.logging import get_logger
from teamshared.memory.audit import AuditLog
from teamshared.memory.request_context import RequestContext
from teamshared.memory.types import MemoryItemScope, MemoryKind, MemorySource, Visibility
from teamshared.memory.vectorstore import VectorStore

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


class IngestionPipeline:
    def __init__(
        self,
        vector_store: VectorStore,
        approvals: ApprovalQueue,
        audit: AuditLog,
        authorizer: Authorizer,
    ) -> None:
        self.vector_store = vector_store
        self.approvals = approvals
        self.audit = audit
        self.authorizer = authorizer

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
        await self.authorizer.require(ctx.principal, Permissions.MEMORY_CREATE)

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
            await self.approvals.enqueue(
                ctx.org_id, memory_id, reason=reason, requested_by=ctx.principal.id
            )

        await self.audit.record(
            agent=ctx.principal.attribution, action="memory.create",
            org_id=ctx.org_id, actor_type=ctx.principal.type, actor_id=ctx.principal.id,
            resource_type="memory", target_id=str(memory_id), request_id=ctx.request_id,
            after={"status": status, "scope": scope, "visibility": visibility, "source": source},
        )
        return IngestionResult(
            memory_id=memory_id, status=status, pii=findings, injection=verdict
        )
