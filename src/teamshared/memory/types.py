"""Shared pydantic types used across pillars and MCP tool signatures."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryKind = Literal["fact", "preference", "event", "note", "procedure"]
MemoryScope = Literal["working", "semantic", "episodic", "procedural", "strategic", "work", "all"]

StrategicStatementKind = Literal["vision", "mission", "purpose"]
StrategicEntityType = Literal["statement", "plan", "objective", "key_result", "initiative"]
StrategicPlanStatus = Literal["draft", "pending_approval", "active", "closed", "rejected"]
StrategicEntityStatus = Literal[
    "pending_approval", "active", "superseded", "rejected", "closed", "quarantined"
]
KeyResultTrackStatus = Literal["on_track", "at_risk", "off_track", "done"]

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
