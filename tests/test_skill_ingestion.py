"""Skill writes through the guarded ingestion pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from teamshared.identity.principal import Principal
from teamshared.ingestion.pipeline import IngestionPipeline, IngestionRejected
from teamshared.memory.request_context import RequestContext

ORG = UUID("00000000-0000-0000-0000-000000000001")
PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")


def _ctx() -> RequestContext:
    principal = Principal(
        org_id=ORG,
        type="agent",
        id=PRINCIPAL_ID,
        display="cursor",
        roles=("agent",),
    )
    authorizer = MagicMock()
    authorizer.require = AsyncMock()
    return RequestContext(principal=principal, db=MagicMock(), authorizer=authorizer)


def _pipeline() -> tuple[IngestionPipeline, AsyncMock]:
    skills = MagicMock()
    skills.set_skill = AsyncMock(
        return_value={
            "id": 7,
            "name": "ship-pr",
            "version": 1,
            "description": "x",
            "body_md": "safe body",
            "tool_hints": None,
            "tags": [],
            "created_by": "cursor",
            "created_at": "2026-01-01T00:00:00+00:00",
            "status": "active",
        }
    )
    audit = MagicMock()
    audit.record = AsyncMock()
    pipe = IngestionPipeline(
        MagicMock(),
        audit,
        MagicMock(),
        skills,
        MagicMock(),
        MagicMock(),
    )
    return pipe, skills


async def test_ingest_skill_active() -> None:
    pipe, skills = _pipeline()
    result = await pipe.ingest_skill(
        _ctx(),
        name="ship-pr",
        body_md="Steps to open a pull request.",
        agent="cursor",
    )
    assert result.status == "active"
    assert result.skill["version"] == 1
    skills.set_skill.assert_awaited_once()


async def test_ingest_skill_rejects_hard_secret() -> None:
    pipe, skills = _pipeline()
    with pytest.raises(IngestionRejected, match="hard secret"):
        await pipe.ingest_skill(
            _ctx(),
            name="bad",
            body_md="aws key AKIAIOSFODNN7EXAMPLE in body",
            agent="cursor",
        )
    skills.set_skill.assert_not_awaited()
