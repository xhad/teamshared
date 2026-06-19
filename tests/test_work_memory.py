"""Work pillar: store, ingestion, and approval lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from teamshared.identity.principal import Principal
from teamshared.ingestion.approvals import ApprovalQueue
from teamshared.ingestion.pipeline import IngestionPipeline, IngestionRejected
from teamshared.memory.request_context import RequestContext

ORG = UUID("00000000-0000-0000-0000-000000000001")
PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")
WORK_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


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


def _work_pipeline() -> tuple[IngestionPipeline, AsyncMock, AsyncMock]:
    work = MagicMock()
    work.create = AsyncMock(
        return_value={
            "id": WORK_ID,
            "org_id": ORG,
            "title": "Ship work queue",
            "description_md": "MVP",
            "tags": [],
            "work_status": "todo",
            "priority": "normal",
            "blocked_reason": None,
            "requester_type": "agent",
            "requester_id": PRINCIPAL_ID,
            "assignee_type": "agent",
            "assignee_id": PRINCIPAL_ID,
            "due_at": None,
            "repo": None,
            "github": None,
            "source": "agent",
            "status": "pending_approval",
            "created_by": "cursor",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "closed_at": None,
            "initiative_id": None,
        }
    )
    approvals = MagicMock()
    approvals.enqueue_work = AsyncMock(return_value=UUID(int=2))
    audit = MagicMock()
    audit.record = AsyncMock()
    pipe = IngestionPipeline(
        MagicMock(), approvals, audit, MagicMock(), MagicMock(), MagicMock(), work,
    )
    return pipe, work, approvals


async def test_ingest_work_create_pending_for_agents() -> None:
    pipe, work, approvals = _work_pipeline()
    result = await pipe.ingest_work_create(
        _ctx(),
        title="Ship work queue",
        description_md="MVP",
        tags=None,
        work_status="todo",
        priority="normal",
        requester_type="agent",
        requester_id=PRINCIPAL_ID,
        assignee_type="agent",
        assignee_id=PRINCIPAL_ID,
        initiative_id=None,
        due_at=None,
        repo=None,
        github=None,
        agent="cursor",
        require_approval=True,
    )
    assert result.status == "pending_approval"
    work.create.assert_awaited_once()
    kwargs = work.create.await_args.kwargs
    assert kwargs["status"] == "pending_approval"
    approvals.enqueue_work.assert_awaited_once()


async def test_ingest_work_create_rejects_secret() -> None:
    pipe, work, _ = _work_pipeline()
    with pytest.raises(IngestionRejected, match="hard secret"):
        await pipe.ingest_work_create(
            _ctx(),
            title="bad",
            description_md="key AKIAIOSFODNN7EXAMPLE",
            tags=None,
            work_status="todo",
            priority="normal",
            requester_type=None,
            requester_id=None,
            assignee_type=None,
            assignee_id=None,
            initiative_id=None,
            due_at=None,
            repo=None,
            github=None,
            agent="cursor",
        )
    work.create.assert_not_awaited()


async def test_approval_decide_work_activate(monkeypatch: pytest.MonkeyPatch) -> None:
    activate_mock = AsyncMock()
    reject_mock = AsyncMock()

    class _FakeWorkStore:
        def __init__(self, _db: object) -> None:
            pass

        async def activate(self, org_id: UUID, work_id: UUID) -> None:
            await activate_mock(org_id, work_id)

        async def reject(self, org_id: UUID, work_id: UUID) -> None:
            await reject_mock(org_id, work_id)

    monkeypatch.setattr("teamshared.ingestion.approvals.WorkStore", _FakeWorkStore)

    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone = AsyncMock(return_value=(None, None, None, None, None, str(WORK_ID)))
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)
    queue = ApprovalQueue(db)
    result = await queue.decide(ORG, uuid4(), approved=True, decided_by=PRINCIPAL_ID)
    assert result is None
    activate_mock.assert_awaited_once_with(ORG, WORK_ID)


async def test_enrich_labels_uses_display_name_not_name() -> None:
    from teamshared.memory.work import WorkStore

    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    cur.fetchall = AsyncMock(return_value=[(str(user_id), "owner@example.com")])
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)

    store = WorkStore(db)
    items = [{
        "assignee_type": "user",
        "assignee_id": user_id,
        "requester_type": None,
        "requester_id": None,
        "initiative_id": None,
    }]
    await store.enrich_labels(ORG, items)
    user_sql = conn.execute.await_args_list[-1].args[0]
    assert "coalesce(display_name, email)" in user_sql
    assert items[0]["assignee_label"] == "owner@example.com"


async def test_list_items_excludes_closed_by_default() -> None:
    from teamshared.memory.work import WorkStore

    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=cur)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    db.org = MagicMock(return_value=conn)

    store = WorkStore(db)
    await store.list_items(ORG, exclude_closed=True)
    sql = conn.execute.await_args.args[0]
    assert "work_status NOT IN ('done', 'cancelled')" in sql


async def test_work_close_emits_episodic_event() -> None:
    from teamshared.memory.facade import MemoryFacade

    closed_row = {
        "id": WORK_ID,
        "title": "Ship work queue",
        "work_status": "done",
        "assignee_label": "cursor",
        "initiative_title": None,
        "blocked_reason": None,
        "repo": None,
        "github": None,
    }
    work = MagicMock()
    work.close = AsyncMock(return_value=closed_row)
    work.enrich_labels = AsyncMock()
    ingestion = MagicMock()
    ingestion.ingest = AsyncMock(return_value=MagicMock(status="active"))
    services = MagicMock()
    services.tenant_db = MagicMock()
    services.work = work
    services.ingestion = MagicMock(return_value=ingestion)
    services.audit.record = AsyncMock()
    services.authorizer = MagicMock(return_value=MagicMock(require=AsyncMock()))
    facade = MemoryFacade(
        services=services,
        resolver=MagicMock(),
        working=MagicMock(),
        agent_state=MagicMock(),
        procedural=MagicMock(),
        skills=MagicMock(),
        strategic=MagicMock(),
        graph=None,
    )
    principal = Principal(
        org_id=ORG, type="user", id=PRINCIPAL_ID, display="owner@example.com", roles=("member",),
    )
    await facade.work_close(principal, work_id=str(WORK_ID), work_status="done", agent_override=None)
    ingestion.ingest.assert_awaited_once()
    kwargs = ingestion.ingest.await_args.kwargs
    assert kwargs["kind"] == "event"
    assert kwargs["pillar"] == "episodic"
    assert "work:" in kwargs["tags"][1]
