"""Pydantic models for the org/team/project/membership hierarchy."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

OrgStatus = Literal["active", "suspended", "deleted"]


class Organization(BaseModel):
    id: UUID
    slug: str
    name: str
    status: OrgStatus = "active"
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class User(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    display_name: str | None = None
    status: str = "active"
    created_at: datetime | None = None


class Membership(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    role: str = "member"
    created_at: datetime | None = None


class Team(BaseModel):
    id: UUID
    org_id: UUID
    slug: str
    name: str
    created_at: datetime | None = None


class Project(BaseModel):
    id: UUID
    org_id: UUID
    team_id: UUID | None = None
    slug: str
    name: str
    created_at: datetime | None = None
