"""Shared pydantic types used across pillars and MCP tool signatures."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MemoryKind = Literal["fact", "preference", "event", "note", "procedure"]
MemoryScope = Literal["working", "semantic", "episodic", "procedural", "all"]


class MemoryRecord(BaseModel):
    """A single retrievable memory snippet, regardless of pillar."""

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
