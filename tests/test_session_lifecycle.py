"""Facade tests for the one-call session lifecycle.

Covers the self-healing ``session_append``, the ``memory_session_ensure``
bootstrap (state pointer + reuse/rotate), and the ``context_commit`` turn-end
batch (``session_commit``).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.identity.principal import Principal
from teamshared.memory.facade import MemoryFacade

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
AGENT = "cursor"
STATE_ID = "tok_state"
REPO = "Users-me-code-myrepo"


def _principal() -> Principal:
    return Principal(org_id=ORG, type="agent", id=ORG, display=AGENT)


def _facade(
    *,
    working: MagicMock | None = None,
    agent_state: MagicMock | None = None,
) -> tuple[MemoryFacade, MagicMock, MagicMock]:
    working = working or MagicMock()
    agent_state = agent_state or MagicMock()
    ingestion = MagicMock()
    ingestion.ingest = AsyncMock(
        return_value=MagicMock(status="active", memory_id=uuid.uuid4())
    )
    services = MagicMock()
    services.ingestion = MagicMock(return_value=ingestion)
    services.audit.record = AsyncMock()
    services.authorizer = MagicMock(return_value=MagicMock(require=AsyncMock()))
    facade = MemoryFacade(
        services=services,
        resolver=MagicMock(),
        working=working,
        agent_state=agent_state,
        procedural=MagicMock(),
        skills=MagicMock(),
        strategic=MagicMock(),
        graph=None,
    )
    return facade, working, agent_state


def _open_meta(agent: str = AGENT) -> dict[str, str]:
    return {"agent": agent, "closed_at": "", "topic": "t"}


# --- session_append self-healing --------------------------------------------


@pytest.mark.asyncio
async def test_session_append_happy_path_keeps_session() -> None:
    facade, working, _ = _facade()
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.append_turn = AsyncMock(return_value=3)
    out = await facade.session_append(
        _principal(), session_id="sess_a", role="user", content="hi"
    )
    assert out == {"turn_count": 3, "session_id": "sess_a"}


@pytest.mark.asyncio
async def test_session_append_reopens_on_expired_session() -> None:
    facade, working, _ = _facade()
    working.get_metadata = AsyncMock(side_effect=KeyError("unknown session"))
    working.open_session = AsyncMock(return_value="sess_new")
    working.append_turn = AsyncMock(return_value=1)
    out = await facade.session_append(
        _principal(), session_id="sess_gone", role="assistant", content="done"
    )
    assert out["session_id"] == "sess_new"
    assert out["reopened"] is True
    assert out["turn_count"] == 1
    working.append_turn.assert_awaited_once_with(ORG, "sess_new", "assistant", "done")


@pytest.mark.asyncio
async def test_session_append_reopens_on_closed_session() -> None:
    facade, working, _ = _facade()
    working.get_metadata = AsyncMock(return_value={"agent": AGENT, "closed_at": "now"})
    working.open_session = AsyncMock(return_value="sess_new")
    working.append_turn = AsyncMock(side_effect=[ValueError("closed"), 1])
    out = await facade.session_append(
        _principal(), session_id="sess_closed", role="user", content="hi"
    )
    assert out["session_id"] == "sess_new"
    assert out["reopened"] is True


@pytest.mark.asyncio
async def test_session_append_still_rejects_foreign_session() -> None:
    facade, working, _ = _facade()
    working.get_metadata = AsyncMock(return_value=_open_meta(agent="hermes"))
    with pytest.raises(PermissionError):
        await facade.session_append(
            _principal(), session_id="sess_theirs", role="user", content="hi"
        )


# --- session_ensure -----------------------------------------------------------


@pytest.mark.asyncio
async def test_session_ensure_reuses_open_session_from_state() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value={"session_id": "sess_live"})
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.open_session = AsyncMock()
    out = await facade.session_ensure(
        _principal(), state_id=STATE_ID, repo=REPO, topic="new topic"
    )
    assert out == {"session_id": "sess_live", "agent": AGENT, "resumed": True}
    working.open_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_ensure_fresh_rotates_and_updates_state() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value={"session_id": "sess_old"})
    agent_state.set = AsyncMock()
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.close_session = AsyncMock(return_value={})
    working.open_session = AsyncMock(return_value="sess_new")
    out = await facade.session_ensure(
        _principal(), state_id=STATE_ID, repo=REPO, topic="t", fresh=True
    )
    assert out["session_id"] == "sess_new"
    assert out["resumed"] is False
    working.close_session.assert_awaited_once_with(ORG, "sess_old", distill=True)
    stored = agent_state.set.await_args.args
    assert stored[3] == {"session_id": "sess_new"}


@pytest.mark.asyncio
async def test_session_ensure_opens_new_when_state_empty() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value=None)
    agent_state.set = AsyncMock()
    working.open_session = AsyncMock(return_value="sess_new")
    out = await facade.session_ensure(
        _principal(), state_id=STATE_ID, repo=REPO, topic="t"
    )
    assert out["session_id"] == "sess_new"
    assert out["resumed"] is False


@pytest.mark.asyncio
async def test_session_ensure_rotates_expired_pointer() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value={"session_id": "sess_gone"})
    agent_state.set = AsyncMock()
    working.get_metadata = AsyncMock(side_effect=KeyError("unknown"))
    working.close_session = AsyncMock(side_effect=KeyError("unknown"))
    working.open_session = AsyncMock(return_value="sess_new")
    out = await facade.session_ensure(
        _principal(), state_id=STATE_ID, repo=REPO, topic="t"
    )
    assert out["session_id"] == "sess_new"
    assert out["resumed"] is False


@pytest.mark.asyncio
async def test_session_ensure_does_not_reuse_foreign_session() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value={"session_id": "sess_theirs"})
    agent_state.set = AsyncMock()
    working.get_metadata = AsyncMock(return_value=_open_meta(agent="hermes"))
    working.close_session = AsyncMock(return_value={})
    working.open_session = AsyncMock(return_value="sess_mine")
    out = await facade.session_ensure(
        _principal(), state_id=STATE_ID, repo=REPO, topic="t"
    )
    assert out["session_id"] == "sess_mine"


@pytest.mark.asyncio
async def test_session_ensure_appends_user_turn() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value=None)
    agent_state.set = AsyncMock()
    working.open_session = AsyncMock(return_value="sess_new")
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.append_turn = AsyncMock(return_value=1)
    out = await facade.session_ensure(
        _principal(),
        state_id=STATE_ID,
        repo=REPO,
        topic="audit topic",
        user="hello from user",
    )
    assert out["session_id"] == "sess_new"
    assert out["turn_count"] == 1
    working.append_turn.assert_awaited_once_with(ORG, "sess_new", "user", "hello from user")


@pytest.mark.asyncio
async def test_session_append_reopen_preserves_repo_from_stale_meta() -> None:
    facade, working, agent_state = _facade()
    working.get_metadata = AsyncMock(
        return_value={"agent": AGENT, "closed_at": "now", "repo": REPO, "github": "x/y", "topic": "t"},
    )
    working.open_session = AsyncMock(return_value="sess_new")
    working.append_turn = AsyncMock(side_effect=[ValueError("closed"), 1])
    await facade.session_append(
        _principal(), session_id="sess_closed", role="user", content="hi"
    )
    working.open_session.assert_awaited_once_with(
        ORG, AGENT, topic="t", repo=REPO, github="x/y"
    )


@pytest.mark.asyncio
async def test_session_append_reopen_updates_state_pointer() -> None:
    facade, working, agent_state = _facade()
    agent_state.set = AsyncMock()
    working.get_metadata = AsyncMock(side_effect=KeyError("unknown"))
    working.open_session = AsyncMock(return_value="sess_new")
    working.append_turn = AsyncMock(return_value=1)
    await facade.session_append(
        _principal(),
        session_id="sess_gone",
        role="user",
        content="hi",
        state_id=STATE_ID,
        repo=REPO,
    )
    stored = agent_state.set.await_args.args
    assert stored[3] == {"session_id": "sess_new"}


# --- session_commit -----------------------------------------------------------


@pytest.mark.asyncio
async def test_session_commit_appends_summary_and_writes_facts() -> None:
    facade, working, _ = _facade()
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.append_turn = AsyncMock(return_value=4)
    out = await facade.session_commit(
        _principal(),
        state_id=STATE_ID,
        session_id="sess_a",
        summary="Fixed the bug.",
        facts=[{"content": "CI uses freezegun", "kind": "fact"}],
        repo=REPO,
    )
    assert out["session_id"] == "sess_a"
    assert out["turn_count"] == 4
    assert out["closed"] is False
    assert out["memories"][0]["status"] == "active"
    working.append_turn.assert_awaited_once_with(
        ORG, "sess_a", "assistant", "Fixed the bug."
    )


@pytest.mark.asyncio
async def test_session_commit_close_clears_state_pointer() -> None:
    facade, working, agent_state = _facade()
    agent_state.set = AsyncMock()
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.append_turn = AsyncMock(return_value=2)
    working.close_session = AsyncMock(
        return_value={"session_id": "sess_a", "turn_count": 2, "distill_enqueued": True}
    )
    out = await facade.session_commit(
        _principal(),
        state_id=STATE_ID,
        session_id="sess_a",
        summary="Bye.",
        repo=REPO,
        close=True,
    )
    assert out["closed"] is True
    working.close_session.assert_awaited_once_with(ORG, "sess_a", distill=True)
    assert agent_state.set.await_args.args[3] == {}


@pytest.mark.asyncio
async def test_session_commit_resolves_session_from_state() -> None:
    facade, working, agent_state = _facade()
    agent_state.get = AsyncMock(return_value={"session_id": "sess_state"})
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.append_turn = AsyncMock(return_value=1)
    out = await facade.session_commit(
        _principal(), state_id=STATE_ID, session_id=None, summary="s", repo=REPO
    )
    assert out["session_id"] == "sess_state"


@pytest.mark.asyncio
async def test_session_commit_heals_expired_session_and_updates_state() -> None:
    facade, working, agent_state = _facade()
    agent_state.set = AsyncMock()
    working.get_metadata = AsyncMock(side_effect=KeyError("unknown"))
    working.open_session = AsyncMock(return_value="sess_new")
    working.append_turn = AsyncMock(return_value=1)
    out = await facade.session_commit(
        _principal(), state_id=STATE_ID, session_id="sess_gone", summary="s", repo=REPO
    )
    assert out["session_id"] == "sess_new"
    assert out["reopened"] is True
    assert agent_state.set.await_args.args[3] == {"session_id": "sess_new"}


@pytest.mark.asyncio
async def test_session_commit_skips_empty_facts() -> None:
    facade, working, _ = _facade()
    working.get_metadata = AsyncMock(return_value=_open_meta())
    working.append_turn = AsyncMock(return_value=1)
    out = await facade.session_commit(
        _principal(),
        state_id=STATE_ID,
        session_id="sess_a",
        summary="s",
        facts=[{"content": "   "}],
    )
    assert out["memories"] == [{"status": "skipped", "reason": "empty content"}]


# --- work "mine" + follower defaults ------------------------------------------


@pytest.mark.asyncio
async def test_work_list_mine_matches_created_by_label() -> None:
    facade, _, _ = _facade()
    facade.services.work.list_items = AsyncMock(return_value=[])
    await facade.work_list(
        _principal(),
        work_status=None,
        assignee=None,
        mine=True,
        initiative_id=None,
        exclude_closed=True,
        sort="updated_at",
        sort_dir="desc",
        limit=10,
    )
    kwargs: dict[str, Any] = facade.services.work.list_items.await_args.kwargs
    assert kwargs["created_by"] == AGENT
    assert kwargs["assignee_type"] == "agent"


@pytest.mark.asyncio
async def test_work_follower_add_defaults_to_caller() -> None:
    facade, _, _ = _facade()
    facade.services.work.add_follower = AsyncMock(return_value={"id": "f1"})
    await facade.work_follower_add(
        _principal(),
        work_id=str(uuid.uuid4()),
        follower_email=None,
        agent_override=None,
    )
    kwargs = facade.services.work.add_follower.await_args.kwargs
    assert kwargs["follower_type"] == "agent"
    assert kwargs["follower_id"] == ORG


@pytest.mark.asyncio
async def test_work_follower_add_rejects_unknown_email() -> None:
    facade, _, _ = _facade()
    facade.services.work.resolve_user_id_by_email = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="no org member"):
        await facade.work_follower_add(
            _principal(),
            work_id=str(uuid.uuid4()),
            follower_email="nobody@example.com",
            agent_override=None,
        )
