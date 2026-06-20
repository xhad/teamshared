"""Distiller convergence (G2 Slice 4): distilled output is ingested org-scoped.

The worker no longer writes through the legacy SemanticEpisodicStore; it builds
an agent Principal for the job's org and writes the episode + facts + decisions
through the RLS ingestion pipeline. These tests drive `_handle` directly with
mocked stores, asserting the right pillars/scopes land under the job's org.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.distill import worker as worker_mod
from teamshared.distill.worker import DistillWorker
from teamshared.identity.principal import Principal
from tests.compress_settings import apply_compress_settings

JOB_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")
DEFAULT_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _worker(ingest: AsyncMock, *, org: uuid.UUID) -> DistillWorker:
    w = object.__new__(DistillWorker)
    w.settings = SimpleNamespace(default_org_id=DEFAULT_ORG)
    apply_compress_settings(w.settings)

    w.working = MagicMock()
    w.working.client = MagicMock()
    w.working.get_turns = AsyncMock(
        return_value=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    )
    w.working.mark_subject_dirty = AsyncMock(return_value=False)

    ingestion = MagicMock()
    ingestion.ingest = ingest
    services = MagicMock()
    services.ingestion = MagicMock(return_value=ingestion)
    services.authorizer = MagicMock(return_value=MagicMock())
    w.services = services

    w.resolver = MagicMock()
    w.resolver.agent_principal = AsyncMock(
        return_value=Principal(org_id=org, type="agent", id=uuid.uuid4(), display="cursor",
                               roles=("agent",))
    )
    return w


@pytest.fixture(autouse=True)
def _stub_summarize(monkeypatch) -> None:
    monkeypatch.setattr(
        worker_mod,
        "summarize",
        AsyncMock(
            return_value={
                "episode": {"summary": "we planned the migration", "tags": ["infra"],
                            "outcome": "done"},
                "facts": [{"content": "prod runs on Spark", "kind": "fact"}],
                "decisions": [{"content": "use pgvector", "rationale": "RLS"}],
            }
        ),
    )


async def test_distilled_output_ingested_under_job_org() -> None:
    ingest = AsyncMock()
    w = _worker(ingest, org=JOB_ORG)

    await w._handle({"session_id": "sess1", "agent": "cursor", "topic": "migration",
                     "org_id": str(JOB_ORG)})

    # Worker resolved the agent Principal inside the job's org.
    w.resolver.agent_principal.assert_awaited_once_with(JOB_ORG, "cursor")
    # Episode + 1 fact + 1 decision = 3 ingest calls.
    assert ingest.await_count == 3
    # Every ingest ran under a RequestContext scoped to the job org.
    for call in ingest.await_args_list:
        ctx = call.args[0]
        assert ctx.principal.org_id == JOB_ORG

    pillars = {call.kwargs["pillar"] for call in ingest.await_args_list}
    assert pillars == {"episodic", "semantic"}


async def test_org_id_defaults_when_missing_from_job() -> None:
    ingest = AsyncMock()
    w = _worker(ingest, org=DEFAULT_ORG)

    await w._handle({"session_id": "sess2", "agent": "cursor", "topic": "x"})

    w.resolver.agent_principal.assert_awaited_once_with(DEFAULT_ORG, "cursor")
    w.working.get_turns.assert_awaited_once_with(DEFAULT_ORG, "sess2")


async def test_empty_transcript_skips_ingestion() -> None:
    ingest = AsyncMock()
    w = _worker(ingest, org=JOB_ORG)
    w.working.get_turns = AsyncMock(return_value=[])

    await w._handle({"session_id": "sess3", "agent": "cursor", "org_id": str(JOB_ORG)})

    ingest.assert_not_awaited()


async def test_distill_enqueues_curation_for_subjects() -> None:
    ingest = AsyncMock()
    w = _worker(ingest, org=JOB_ORG)

    await w._handle({"session_id": "sess4", "agent": "cursor", "topic": "migration",
                     "org_id": str(JOB_ORG)})

    # The decision is filed under the topic subject, so curation is marked for it.
    w.working.mark_subject_dirty.assert_awaited()
    subjects = {call.args[1] for call in w.working.mark_subject_dirty.await_args_list}
    assert "migration" in subjects
