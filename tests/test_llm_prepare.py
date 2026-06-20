"""Tests for POST /llm/prepare (Cursor hook pipeline)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import BearerAuthMiddleware
from teamshared.identity.principal import Principal
from teamshared.server.llm_prepare_api import handle_llm_prepare

ORG = UUID("00000000-0000-0000-0000-000000000001")


def _principal() -> Principal:
    return Principal(org_id=ORG, type="agent", id=UUID(int=1), display="cursor")


def _mock_state(*, prepare_enabled: bool = True) -> SimpleNamespace:
    settings = SimpleNamespace(
        llm_prepare_enabled=prepare_enabled,
        compress_min_chars=800,
    )
    return SimpleNamespace(
        settings=settings,
        working=MagicMock(),
        facade=MagicMock(),
    )


def _prepared_result() -> dict:
    return {
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "sess-1",
        "additional_context": "## TeamShared context\n\n- prior fact\n",
        "stats": {
            "session_appended": True,
            "enriched": True,
            "compressed": False,
            "chars_saved": 20,
            "original_chars": 100,
            "compressed_chars": 80,
        },
    }


def _client(*, prepare_enabled: bool = True) -> TestClient:
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=_principal())
    resolver.anonymous = AsyncMock(return_value=_principal())
    app = Starlette(
        routes=[Route("/llm/prepare", handle_llm_prepare, methods=["POST"])],
        middleware=[
            Middleware(
                BearerAuthMiddleware,
                resolver=resolver,
                auth_disabled=False,
            )
        ],
    )
    return TestClient(app)


@patch("teamshared.server.llm_prepare_api.run_context_prepare", new_callable=AsyncMock)
@patch("teamshared.server.llm_prepare_api.get_state")
def test_llm_prepare_requires_bearer(
    mock_get_state: MagicMock,
    mock_prepare: AsyncMock,
) -> None:
    mock_get_state.return_value = _mock_state()
    mock_prepare.return_value = _prepared_result()
    with _client() as client:
        resp = client.post("/llm/prepare", json={"prompt": "hi"})
    assert resp.status_code == 401


@patch("teamshared.server.llm_prepare_api.run_context_prepare", new_callable=AsyncMock)
@patch("teamshared.server.llm_prepare_api.get_state")
def test_llm_prepare_accepts_prompt(
    mock_get_state: MagicMock,
    mock_prepare: AsyncMock,
) -> None:
    mock_get_state.return_value = _mock_state()
    mock_prepare.return_value = _prepared_result()
    with _client() as client:
        resp = client.post(
            "/llm/prepare",
            json={"prompt": "how do we deploy?", "repo": "Users-chad-code-teamshared"},
            headers={"Authorization": "Bearer tsk_test"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert body["stats"]["session_appended"] is True
    assert body["stats"]["enriched"] is True
    assert "TeamShared context" in (body.get("additional_context") or "")
    mock_prepare.assert_awaited_once()
    assert mock_prepare.await_args.kwargs["repo"] == "Users-chad-code-teamshared"


@patch("teamshared.server.llm_prepare_api.get_state")
def test_llm_prepare_disabled_returns_503(mock_get_state: MagicMock) -> None:
    mock_get_state.return_value = _mock_state(prepare_enabled=False)
    with _client() as client:
        resp = client.post(
            "/llm/prepare",
            json={"prompt": "hi"},
            headers={"Authorization": "Bearer tsk_test"},
        )
    assert resp.status_code == 503
    assert resp.json()["error"] == "llm_prepare_disabled"


def test_classify_llm_prepare_path() -> None:
    from teamshared.server.route_policy import RouteClass, classify_path

    assert classify_path("/llm/prepare") == RouteClass.MCP_BEARER
