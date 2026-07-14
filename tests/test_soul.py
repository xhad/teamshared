"""Unit tests for private per-person soul memory."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from teamshared.identity.principal import Principal
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.soul import (
    DEFAULT_SOUL_MAX_CHARS,
    absorb_observation,
    compress_soul,
    estimate_tokens,
)

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
STATE_ID = "tok_state"
REPO = "Users-me-code-myrepo"


def test_compress_soul_caps_length() -> None:
    body = "# Soul\n" + ("x" * 5000)
    out = compress_soul(body, max_chars=100)
    assert len(out) <= 100
    assert "trimmed" in out


def test_absorb_observation_appends_notes() -> None:
    merged = absorb_observation("# Soul\nname: Ada\n", "Prefers dark mode")
    assert "## Notes" in merged
    assert "dark mode" in merged
    assert estimate_tokens(merged) > 0


def test_absorb_is_idempotent_for_same_bullet() -> None:
    once = absorb_observation(None, "likes terse replies", max_chars=DEFAULT_SOUL_MAX_CHARS)
    twice = absorb_observation(once, "likes terse replies", max_chars=DEFAULT_SOUL_MAX_CHARS)
    assert once.count("likes terse replies") == 1
    assert twice.count("likes terse replies") == 1


def _principal(*, linked: bool = True) -> Principal:
    return Principal(
        org_id=ORG,
        type="agent",
        id=ORG,
        display="cursor",
        account_id=ACCOUNT if linked else None,
    )


def _facade(*, soul_row: dict | None = None) -> tuple[MemoryFacade, MagicMock]:
    soul = MagicMock()
    soul.get = AsyncMock(return_value=soul_row)
    soul.upsert = AsyncMock(
        return_value={
            "org_id": str(ORG),
            "account_id": str(ACCOUNT),
            "body_md": "# Soul\nname: Ada\n",
            "version": 2,
            "token_est": 12,
            "updated_by": "cursor",
            "updated_at": None,
        }
    )
    soul.absorb = AsyncMock(
        return_value={
            "body_md": "# Soul\n## Notes\n- Prefers dark mode\n",
            "token_est": 20,
            "version": 3,
        }
    )
    services = MagicMock()
    services.soul = soul
    services.settings.soul_max_chars = DEFAULT_SOUL_MAX_CHARS
    services.audit.record = AsyncMock()
    services.authorizer = MagicMock(return_value=MagicMock(require=AsyncMock()))
    services.ingestion = MagicMock(
        return_value=MagicMock(
            ingest=AsyncMock(
                return_value=MagicMock(status="active", memory_id=uuid.uuid4())
            )
        )
    )
    working = MagicMock()
    agent_state = MagicMock()
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
    return facade, soul


@pytest.mark.asyncio
async def test_session_ensure_returns_soul_when_linked() -> None:
    soul_row = {
        "body_md": "# Soul\nname: Ada\n",
        "token_est": 10,
        "version": 1,
        "updated_at": None,
    }
    facade, soul = _facade(soul_row=soul_row)
    working = facade.working
    agent_state = facade.agent_state
    agent_state.get = AsyncMock(return_value=None)
    working.open_session = AsyncMock(return_value="sess_1")
    agent_state.set = AsyncMock()

    out = await facade.session_ensure(
        _principal(),
        state_id=STATE_ID,
        repo=REPO,
        topic="hi",
        fresh=True,
    )
    assert out["session_id"] == "sess_1"
    assert out["soul_linked"] is True
    assert out["soul"] == "# Soul\nname: Ada\n"
    assert out["soul_tokens"] == 10
    soul.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_ensure_soul_unlinked_when_no_account() -> None:
    facade, soul = _facade()
    facade.agent_state.get = AsyncMock(return_value=None)
    facade.working.open_session = AsyncMock(return_value="sess_1")
    facade.agent_state.set = AsyncMock()

    out = await facade.session_ensure(
        _principal(linked=False),
        state_id=STATE_ID,
        repo=REPO,
        topic="hi",
        fresh=True,
    )
    assert out["soul_linked"] is False
    assert out["soul"] is None
    soul.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_soul_set_requires_account() -> None:
    facade, _ = _facade()
    with pytest.raises(PermissionError, match="linked human account"):
        await facade.soul_set(_principal(linked=False), body_md="# Soul\n")


@pytest.mark.asyncio
async def test_remember_preference_absorbs_into_soul() -> None:
    facade, soul = _facade()
    out = await facade.remember(
        _principal(),
        content="User prefers dark mode",
        kind="preference",
        subject="user",
        tags=["preference"],
        agent_override=None,
    )
    assert out["status"] == "active"
    assert out["soul_updated"] is True
    soul.absorb.assert_awaited_once()
    # Ingest tags include account:<uuid>
    ingest = facade.services.ingestion.return_value.ingest
    tags = ingest.await_args.kwargs.get("tags") or ingest.await_args.args
    # tags are positional kwargs
    call_kwargs = ingest.await_args.kwargs
    assert f"account:{ACCOUNT}" in (call_kwargs.get("tags") or [])
