"""Tests for the OpenAI-compatible chat-completions gateway (/gateway/v1)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.auth import BearerAuthMiddleware
from teamshared.identity.principal import Principal
from teamshared.memory import working as working_mod
from teamshared.memory.working import WorkingMemory
from teamshared.server.gateway_api import (
    _StreamAccumulator,
    conversation_fingerprint,
    extract_assistant_text,
    handle_gateway_chat_completions,
    handle_gateway_models,
)

ORG = UUID("00000000-0000-0000-0000-000000000001")


def _principal() -> Principal:
    return Principal(org_id=ORG, type="agent", id=UUID(int=1), display="openclaw")


def _settings(**overrides: Any) -> SimpleNamespace:
    base = dict(
        gateway_enabled=True,
        gateway_upstream_base_url="https://upstream.example/v1",
        gateway_upstream_api_key="sk-upstream",
        gateway_default_model="gpt-test",
        gateway_upstream_timeout_seconds=30,
        llm_prepare_enabled=True,
        llm_prepare_context_token_budget=1500,
        compress_min_chars=800,
        compress_ccr_ttl_seconds=3600,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _state(**overrides: Any) -> SimpleNamespace:
    working = MagicMock()
    working.resolve_conversation_session = AsyncMock(return_value="sess-conv-1")
    working.client = MagicMock()
    facade = MagicMock()
    facade.session_append = AsyncMock(return_value={"turn_count": 2})
    return SimpleNamespace(
        settings=overrides.pop("settings", _settings()),
        working=working,
        facade=facade,
        **overrides,
    )


def _prepared(messages: list[dict[str, Any]], session_id: str = "sess-conv-1") -> SimpleNamespace:
    return SimpleNamespace(messages=messages, session_id=session_id)


def _client() -> TestClient:
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=_principal())
    resolver.anonymous = AsyncMock(return_value=_principal())
    app = Starlette(
        routes=[
            Route(
                "/gateway/v1/chat/completions",
                handle_gateway_chat_completions,
                methods=["POST"],
            ),
            Route("/gateway/v1/models", handle_gateway_models, methods=["GET"]),
        ],
        middleware=[
            Middleware(BearerAuthMiddleware, resolver=resolver, auth_disabled=False)
        ],
    )
    return TestClient(app)


def _mock_transport(handler: Any) -> Any:
    """Patch the gateway's httpx.AsyncClient to route through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient  # patching the module attr is global; keep the real class

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return real_client(transport=transport, **kwargs)

    return patch("teamshared.server.gateway_api.httpx.AsyncClient", side_effect=factory)


# --- helpers ------------------------------------------------------------


def test_conversation_fingerprint_stable_and_distinct() -> None:
    msgs_a = [{"role": "system", "content": "s"}, {"role": "user", "content": "hello"}]
    msgs_a_longer = [*msgs_a, {"role": "assistant", "content": "hi"}, {"role": "user", "content": "more"}]
    msgs_b = [{"role": "user", "content": "different opener"}]
    assert conversation_fingerprint(msgs_a) == conversation_fingerprint(msgs_a_longer)
    assert conversation_fingerprint(msgs_a) != conversation_fingerprint(msgs_b)


def test_conversation_fingerprint_content_parts() -> None:
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    assert conversation_fingerprint(msgs) == conversation_fingerprint(
        [{"role": "user", "content": "hello"}]
    )


def test_extract_assistant_text_content_and_tool_calls() -> None:
    assert (
        extract_assistant_text(
            {"choices": [{"message": {"role": "assistant", "content": "answer"}}]}
        )
        == "answer"
    )
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"function": {"name": "read_file"}}],
                }
            }
        ]
    }
    assert extract_assistant_text(payload) == "[tool_calls] read_file"


def test_stream_accumulator_rebuilds_text() -> None:
    acc = _StreamAccumulator()
    frames = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
    ]
    for frame in frames:
        acc.feed(f"data: {json.dumps(frame)}\n\n".encode())
    acc.feed(b"data: [DONE]\n\n")
    assert acc.text() == "Hello"


# --- route behavior ------------------------------------------------------


@patch("teamshared.server.gateway_api.get_state")
def test_gateway_requires_bearer(mock_get_state: MagicMock) -> None:
    mock_get_state.return_value = _state()
    with _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 401


@patch("teamshared.server.gateway_api.get_state")
def test_gateway_disabled_returns_503(mock_get_state: MagicMock) -> None:
    mock_get_state.return_value = _state(settings=_settings(gateway_enabled=False))
    with _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer tsk_test"},
        )
    assert resp.status_code == 503


@patch("teamshared.server.gateway_api.get_state")
def test_gateway_requires_model_when_no_default(mock_get_state: MagicMock) -> None:
    mock_get_state.return_value = _state(settings=_settings(gateway_default_model=None))
    with _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer tsk_test"},
        )
    assert resp.status_code == 400


@patch("teamshared.server.gateway_api.prepare_llm_messages", new_callable=AsyncMock)
@patch("teamshared.server.gateway_api.get_state")
def test_gateway_blocking_proxies_and_appends_assistant(
    mock_get_state: MagicMock, mock_prepare: AsyncMock
) -> None:
    state = _state()
    mock_get_state.return_value = state
    enriched = [
        {"role": "system", "content": "## TeamShared context\n\n- fact"},
        {"role": "user", "content": "hi"},
    ]
    mock_prepare.return_value = _prepared(enriched)

    seen: dict[str, Any] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "cmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
            },
        )

    with _mock_transport(upstream), _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "temperature": 0.1},
            headers={"Authorization": "Bearer tsk_test"},
        )

    assert resp.status_code == 200
    assert resp.json()["id"] == "cmpl-1"
    # Upstream got the enriched messages, default model, and upstream key.
    assert seen["url"] == "https://upstream.example/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-upstream"
    assert seen["body"]["model"] == "gpt-test"
    assert seen["body"]["messages"] == enriched
    assert seen["body"]["temperature"] == 0.1
    # New user turn -> prepare ran with append+enrich against the mapped session.
    kwargs = mock_prepare.await_args.kwargs
    assert kwargs["session_id"] == "sess-conv-1"
    assert kwargs["append_session"] is True
    assert kwargs["enrich"] is True
    # Assistant reply was captured into the same session.
    state.facade.session_append.assert_awaited_once()
    append_kwargs = state.facade.session_append.await_args.kwargs
    assert append_kwargs["session_id"] == "sess-conv-1"
    assert append_kwargs["role"] == "assistant"
    assert append_kwargs["content"] == "the answer"


@patch("teamshared.server.gateway_api.prepare_llm_messages", new_callable=AsyncMock)
@patch("teamshared.server.gateway_api.get_state")
def test_gateway_agentic_continuation_skips_append_and_enrich(
    mock_get_state: MagicMock, mock_prepare: AsyncMock
) -> None:
    state = _state()
    mock_get_state.return_value = state
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "x"}}]},
        {"role": "tool", "content": "tool output", "tool_call_id": "1"},
    ]
    mock_prepare.return_value = _prepared(messages)

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "done"}}]},
        )

    with _mock_transport(upstream), _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": messages},
            headers={"Authorization": "Bearer tsk_test"},
        )

    assert resp.status_code == 200
    kwargs = mock_prepare.await_args.kwargs
    assert kwargs["append_session"] is False
    assert kwargs["enrich"] is False


@patch("teamshared.server.gateway_api.prepare_llm_messages", new_callable=AsyncMock)
@patch("teamshared.server.gateway_api.get_state")
def test_gateway_streaming_relays_sse_and_appends_assistant(
    mock_get_state: MagicMock, mock_prepare: AsyncMock
) -> None:
    state = _state()
    mock_get_state.return_value = state
    mock_prepare.return_value = _prepared([{"role": "user", "content": "hi"}])

    frames = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "str"}}]},
        {"choices": [{"delta": {"content": "eamed"}}]},
    ]
    sse = "".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n"

    def upstream(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            content=sse.encode(),
            headers={"content-type": "text/event-stream"},
        )

    with _mock_transport(upstream), _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"Authorization": "Bearer tsk_test"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in resp.text
    state.facade.session_append.assert_awaited_once()
    assert state.facade.session_append.await_args.kwargs["content"] == "streamed"


@patch("teamshared.server.gateway_api.prepare_llm_messages", new_callable=AsyncMock)
@patch("teamshared.server.gateway_api.get_state")
def test_gateway_upstream_failure_returns_502(
    mock_get_state: MagicMock, mock_prepare: AsyncMock
) -> None:
    state = _state()
    mock_get_state.return_value = state
    mock_prepare.return_value = _prepared([{"role": "user", "content": "hi"}])

    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with _mock_transport(upstream), _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer tsk_test"},
        )

    assert resp.status_code == 502
    assert resp.json()["error"]["type"] == "upstream_error"


@patch("teamshared.server.gateway_api.prepare_llm_messages", new_callable=AsyncMock)
@patch("teamshared.server.gateway_api.get_state")
def test_gateway_prepare_failure_degrades_to_plain_proxy(
    mock_get_state: MagicMock, mock_prepare: AsyncMock
) -> None:
    state = _state()
    mock_get_state.return_value = state
    mock_prepare.side_effect = RuntimeError("memory down")

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # Original (unprepared) messages still reach the upstream.
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    with _mock_transport(upstream), _client() as client:
        resp = client.post(
            "/gateway/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer tsk_test"},
        )

    assert resp.status_code == 200


@patch("teamshared.server.gateway_api.get_state")
def test_gateway_models_lists_default_model(mock_get_state: MagicMock) -> None:
    mock_get_state.return_value = _state()
    with _client() as client:
        resp = client.get(
            "/gateway/v1/models", headers={"Authorization": "Bearer tsk_test"}
        )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "gpt-test"


def test_classify_gateway_paths() -> None:
    from teamshared.server.route_policy import RouteClass, classify_path

    assert classify_path("/gateway/v1/chat/completions") == RouteClass.MCP_BEARER
    assert classify_path("/gateway/v1/models") == RouteClass.MCP_BEARER


# --- WorkingMemory conversation mapping ----------------------------------


@pytest_asyncio.fixture
async def memory(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[WorkingMemory]:
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _from_url(url: str, **kwargs: object) -> fakeredis.aioredis.FakeRedis:
        return fake

    monkeypatch.setattr(working_mod.redis, "from_url", _from_url)
    mem = WorkingMemory("redis://fake", default_ttl=60)
    await mem.connect()
    try:
        yield mem
    finally:
        await mem.close()


@pytest.mark.asyncio
async def test_resolve_conversation_session_reuses_mapping(memory: WorkingMemory) -> None:
    sid1 = await memory.resolve_conversation_session(
        str(ORG), "openclaw", "fp-1", topic="hello"
    )
    sid2 = await memory.resolve_conversation_session(str(ORG), "openclaw", "fp-1")
    assert sid1 == sid2
    sid3 = await memory.resolve_conversation_session(str(ORG), "openclaw", "fp-2")
    assert sid3 != sid1


@pytest.mark.asyncio
async def test_resolve_conversation_session_reopens_after_close(
    memory: WorkingMemory,
) -> None:
    sid1 = await memory.resolve_conversation_session(str(ORG), "openclaw", "fp-1")
    await memory.close_session(str(ORG), sid1, distill=False)
    sid2 = await memory.resolve_conversation_session(str(ORG), "openclaw", "fp-1")
    assert sid2 != sid1


@pytest.mark.asyncio
async def test_append_turn_refreshes_session_ttl(memory: WorkingMemory) -> None:
    sid = await memory.open_session(str(ORG), "openclaw", topic="t", ttl=60)
    # Simulate the session nearing expiry, then an append arriving.
    await memory.client.expire(f"working:{ORG}:session:{sid}", 5)
    await memory.append_turn(str(ORG), sid, "user", "still here")
    ttl = await memory.client.ttl(f"working:{ORG}:session:{sid}")
    assert ttl > 5
    turns_ttl = await memory.client.ttl(f"working:{ORG}:session:{sid}:turns")
    assert turns_ttl > 5
