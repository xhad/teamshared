"""CuratorWorker._handle: load subject memory, synthesize, upsert a wiki page."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.distill import curator_worker as cw_mod
from teamshared.distill.curator_worker import CuratorWorker
from tests.compress_settings import apply_compress_settings

ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")
DEFAULT_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _rec(content: str, kind: str = "fact") -> SimpleNamespace:
    return SimpleNamespace(id=str(uuid.uuid4()), content=content, kind=kind,
                           confidence=0.9, created_at="2026-05-28T10:00:00")


def _worker(*, facts: list, episodes: list, upsert: AsyncMock) -> CuratorWorker:
    w = object.__new__(CuratorWorker)
    w.settings = SimpleNamespace(default_org_id=DEFAULT_ORG)
    apply_compress_settings(w.settings)
    w._MAX_FACTS = 200
    w._MAX_EPISODES = 20
    vs = SimpleNamespace(
        list_by_subject=AsyncMock(return_value=facts),
        list_episodes=AsyncMock(return_value=episodes),
    )
    wiki = SimpleNamespace(upsert_page=upsert)
    w.services = MagicMock()
    w.services.vector_store = vs
    w.services.wiki = wiki
    w.services.working = MagicMock()
    w.services.working.client = MagicMock()
    return w


@pytest.fixture(autouse=True)
def _stub_curate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cw_mod, "curate",
        AsyncMock(return_value={"title": "Infra", "body_md": "# Infra\n\nProd on Spark."}),
    )


async def test_curates_and_upserts_page() -> None:
    upsert = AsyncMock(return_value={"version": 1})
    w = _worker(facts=[_rec("prod on Spark")], episodes=[_rec("migrated", "event")], upsert=upsert)

    await w._handle({"org_id": str(ORG), "subject": "teamshared infra"})

    upsert.assert_awaited_once()
    kwargs = upsert.await_args.kwargs
    assert kwargs["slug"] == "teamshared-infra"
    assert kwargs["title"] == "Infra"
    assert kwargs["body_md"].startswith("# Infra")
    # sources span both facts and episodes for provenance.
    assert len(kwargs["sources"]) == 2
    # page written under the job's org.
    assert upsert.await_args.args[0] == ORG


async def test_skips_when_no_facts() -> None:
    upsert = AsyncMock()
    w = _worker(facts=[], episodes=[], upsert=upsert)
    await w._handle({"org_id": str(ORG), "subject": "empty"})
    upsert.assert_not_awaited()


async def test_skips_blank_subject() -> None:
    upsert = AsyncMock()
    w = _worker(facts=[_rec("x")], episodes=[], upsert=upsert)
    await w._handle({"org_id": str(ORG), "subject": "  "})
    upsert.assert_not_awaited()


async def test_skips_when_curator_returns_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cw_mod, "curate", AsyncMock(return_value={"title": "x", "body_md": ""}))
    upsert = AsyncMock()
    w = _worker(facts=[_rec("x")], episodes=[], upsert=upsert)
    await w._handle({"org_id": str(ORG), "subject": "teamshared infra"})
    upsert.assert_not_awaited()
