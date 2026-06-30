"""Shared pydantic types used across pillars and MCP tool signatures."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryKind = Literal["fact", "preference", "event", "note", "procedure", "skill"]
MemoryScope = Literal[
    "working", "semantic", "episodic", "procedural", "skill", "strategic", "work", "all",
]

StrategicStatementKind = Literal["vision", "mission", "purpose"]
StrategicEntityType = Literal["statement", "plan", "objective", "key_result", "initiative"]
StrategicPlanStatus = Literal["draft", "pending_approval", "active", "closed", "rejected"]
StrategicEntityStatus = Literal[
    "pending_approval", "active", "superseded", "rejected", "closed", "quarantined"
]
KeyResultTrackStatus = Literal["on_track", "at_risk", "off_track", "done"]

WorkStatus = Literal["backlog", "todo", "in_progress", "blocked", "done", "cancelled"]
WorkPriority = Literal["urgent", "high", "normal", "low"]
WorkItemType = Literal["task", "milestone", "approval"]
WorkSort = Literal["updated_at", "priority", "work_status", "created_at"]
WorkSortDir = Literal["asc", "desc"]
SessionRole = Literal["user", "assistant", "tool", "system"]
AssigneeType = Literal["user", "agent"]
ProjectView = Literal["list", "board", "timeline", "calendar"]
ProjectStatusState = Literal["on_track", "at_risk", "off_track"]
ToolCatalogScope = Literal["memory", "work", "all"]

# Default pillars searched when memory_recall scope is omitted.
# Working memory is opt-in (``scope=["working"]``) so open-session tool turns
# do not crowd out durable hits in default recall / think.
DEFAULT_RECALL_SCOPES: tuple[MemoryScope, ...] = (
    "semantic", "episodic", "procedural", "skill", "strategic", "work",
)

# First-party memory metadata (migration 004). ``MemoryItemScope`` is the
# access scope of a stored item; ``MemoryScope`` above is the retrieval pillar.
MemoryItemScope = Literal[
    "global", "org", "team", "project", "user", "agent", "conversation", "session"
]
Visibility = Literal["private", "shared"]
MemorySource = Literal["manual", "agent", "extraction", "connector"]
MemoryStatus = Literal["active", "pending_approval", "quarantined", "soft_deleted"]


class MemoryRecord(BaseModel):
    """A single retrievable memory snippet, regardless of pillar.

    The first batch of fields are pillar-agnostic; the trailing ``org_id`` /
    ``scope`` / ``visibility`` / ``source`` / ``confidence`` / ``version`` /
    ``status`` fields are populated for first-party (pgvector) items and left
    as defaults for the ephemeral working pillar.
    """

    id: str
    pillar: MemoryScope
    kind: MemoryKind | None = None
    content: str
    agent: str | None = None
    subject: str | None = None
    tags: list[str] = Field(default_factory=list)
    score: float | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    org_id: UUID | None = None
    scope: MemoryItemScope | None = None
    scope_ref_id: UUID | None = None
    visibility: Visibility | None = None
    source: MemorySource | None = None
    confidence: float | None = None
    importance: float | None = None
    version: int | None = None
    status: MemoryStatus | None = None


class MemoryItem(BaseModel):
    """A full first-party memory row (the source of truth in ``memory_items``)."""

    id: UUID
    org_id: UUID
    pillar: Literal["semantic", "episodic"] = "semantic"
    kind: MemoryKind = "note"
    scope: MemoryItemScope = "org"
    scope_ref_id: UUID | None = None
    visibility: Visibility = "private"
    content: str
    summary: str | None = None
    subject: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: MemorySource = "manual"
    source_ref: dict[str, Any] | None = None
    confidence: float | None = None
    importance: float | None = None
    owner_type: str | None = None
    owner_id: UUID | None = None
    creator_type: str | None = None
    creator_id: UUID | None = None
    status: MemoryStatus = "active"
    version: int = 1
    content_hash: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class TimeRange(BaseModel):
    """Inclusive ``[since, until]`` window. Either bound may be omitted."""

    since: datetime | None = None
    until: datetime | None = None


class RecallResult(BaseModel):
    """Bundle returned by ``memory_recall``: ranked records + per-pillar counts."""

    query: str
    records: list[MemoryRecord]
    counts_by_pillar: dict[str, int] = Field(default_factory=dict)
    errors_by_pillar: dict[str, str] = Field(default_factory=dict)


ThinkGapKind = Literal["stale", "missing", "contradicts", "low_confidence"]


class ThinkCitation(BaseModel):
    """A source record cited in a synthesized answer."""

    memory_id: str
    pillar: str
    snippet: str
    agent: str | None = None


class ThinkGap(BaseModel):
    """Something the brain does not know or may be wrong about."""

    kind: ThinkGapKind
    claim: str
    detail: str | None = None
    memory_ids: list[str] = Field(default_factory=list)


class ThinkResult(BaseModel):
    """Synthesized answer with citations and explicit gaps (``gbrain think`` parity)."""

    query: str
    answer_md: str
    citations: list[ThinkCitation] = Field(default_factory=list)
    gaps: list[ThinkGap] = Field(default_factory=list)
    sources_used: int = 0
    counts_by_pillar: dict[str, int] = Field(default_factory=dict)
