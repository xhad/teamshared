"""OpenAI-compatible chat-completions gateway (the Tier-2 memory companion).

Harnesses that let you set a custom base URL (e.g. OpenClaw's
``models.providers.<name>.baseUrl``) point their model calls at
``/gateway/v1``. Every request is then run through the pre-LLM pipeline
(session append + history compression + context-pack enrichment) via
:func:`teamshared.llm.gateway.prepare_llm_messages` and proxied to the
configured upstream provider, streaming SSE back verbatim. The assistant
reply is appended to the same working session once the response completes,
so the distiller/curator see the full conversation with zero agent
cooperation.

Session mapping is server-side: each conversation is fingerprinted from its
first user message and bound to one working session per agent
(:meth:`WorkingMemory.resolve_conversation_session`), so parallel
conversations from the same bearer token do not interleave.

Memory work is best-effort: a session or enrichment failure must never break
the proxied completion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from teamshared.auth import current_principal
from teamshared.compress.factory import ccr_store_from_working
from teamshared.identity.principal import Principal
from teamshared.llm.gateway import prepare_llm_messages
from teamshared.logging import get_logger
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.working import WorkingMemory
from teamshared.metrics import METRICS
from teamshared.server.state import ServerState, get_state

log = get_logger(__name__)

# Cap what we store per assistant turn; long replies are summarized by the
# distiller anyway and Redis turns should stay bounded.
MAX_ASSISTANT_TURN_CHARS = 8000

_SSE_DATA_PREFIX = "data:"


def _error_response(message: str, *, status: int, error_type: str = "invalid_request_error") -> JSONResponse:
    """OpenAI-style error envelope so clients surface the message verbatim."""
    return JSONResponse(
        {"error": {"message": message, "type": error_type, "code": status}},
        status_code=status,
    )


def _content_text(content: Any) -> str:
    """Flatten OpenAI message content (string or content-part list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(parts)
    return ""


def conversation_fingerprint(messages: list[dict[str, Any]]) -> str:
    """Stable id for a conversation: hash of its first user message.

    Chat-completions requests replay the whole history each turn, so the
    first user message is constant across a conversation and distinct across
    conversations (modulo identical openers, which the per-agent namespace
    and session TTL keep harmless).
    """
    for msg in messages:
        if msg.get("role") == "user":
            text = _content_text(msg.get("content"))
            if text.strip():
                return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return "no-user-message"


def _conversation_topic(messages: list[dict[str, Any]]) -> str | None:
    for msg in messages:
        if msg.get("role") == "user":
            text = _content_text(msg.get("content")).strip()
            if text:
                return text[:120]
    return None


def _is_new_user_turn(messages: list[dict[str, Any]]) -> bool:
    """True when the request ends with a user message (a genuinely new turn).

    Agentic loops re-POST the history with trailing assistant/tool messages;
    appending or re-enriching on those steps would duplicate the user turn
    and burn context budget.
    """
    return bool(messages) and messages[-1].get("role") == "user"


def extract_assistant_text(payload: dict[str, Any]) -> str:
    """Assistant text (or a compact tool-call summary) from a completion."""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = _content_text(message.get("content"))
    if content.strip():
        return content
    tool_calls = message.get("tool_calls") or []
    names = [
        tc.get("function", {}).get("name", "?")
        for tc in tool_calls
        if isinstance(tc, dict)
    ]
    if names:
        return "[tool_calls] " + ", ".join(names)
    return ""


class _StreamAccumulator:
    """Rebuild assistant text from SSE ``chat.completion.chunk`` frames."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._tool_names: list[str] = []
        self._buffer = ""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._feed_line(line.strip())

    def _feed_line(self, line: str) -> None:
        if not line.startswith(_SSE_DATA_PREFIX):
            return
        data = line[len(_SSE_DATA_PREFIX):].strip()
        if not data or data == "[DONE]":
            return
        try:
            frame = json.loads(data)
        except ValueError:
            return
        choices = frame.get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            self._parts.append(content)
        for tc in delta.get("tool_calls") or []:
            name = tc.get("function", {}).get("name") if isinstance(tc, dict) else None
            if name:
                self._tool_names.append(name)

    def text(self) -> str:
        content = "".join(self._parts)
        if content.strip():
            return content
        if self._tool_names:
            return "[tool_calls] " + ", ".join(dict.fromkeys(self._tool_names))
        return ""


async def _resolve_session(
    working: WorkingMemory,
    principal: Principal,
    messages: list[dict[str, Any]],
) -> str | None:
    """Best-effort conversation→session mapping; never fails the request."""
    try:
        agent = principal.display or principal.attribution
        return await working.resolve_conversation_session(
            principal.org_id,
            agent,
            conversation_fingerprint(messages),
            topic=_conversation_topic(messages),
        )
    except Exception as exc:
        log.warning("gateway_session_resolve_failed", error=str(exc))
        return None


async def _append_assistant_turn(
    facade: MemoryFacade,
    principal: Principal,
    session_id: str | None,
    text: str,
) -> None:
    if not session_id or not text.strip():
        return
    if len(text) > MAX_ASSISTANT_TURN_CHARS:
        text = text[: MAX_ASSISTANT_TURN_CHARS - 1] + "\u2026"
    try:
        await facade.session_append(
            principal, session_id=session_id, role="assistant", content=text
        )
    except Exception as exc:
        log.warning("gateway_assistant_append_failed", error=str(exc))


def _upstream_headers(state: ServerState) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = state.settings.gateway_upstream_api_key
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def handle_gateway_models(request: Request) -> Response:
    """``GET /gateway/v1/models`` — minimal catalog for client probes."""
    state = get_state()
    if not state.settings.gateway_enabled:
        return _error_response("gateway_disabled", status=503, error_type="service_unavailable")
    if current_principal() is None:
        return _error_response("unauthorized", status=401, error_type="authentication_error")
    model = state.settings.gateway_default_model or "teamshared-gateway"
    return JSONResponse(
        {"object": "list", "data": [{"id": model, "object": "model", "owned_by": "teamshared"}]}
    )


async def handle_gateway_chat_completions(request: Request) -> Response:
    """``POST /gateway/v1/chat/completions`` — prepare, proxy, capture."""
    state = get_state()
    settings = state.settings
    if not settings.gateway_enabled:
        return _error_response("gateway_disabled", status=503, error_type="service_unavailable")
    if not settings.gateway_upstream_base_url:
        return _error_response(
            "gateway upstream is not configured", status=503, error_type="service_unavailable"
        )

    principal = current_principal()
    if principal is None:
        return _error_response("unauthorized", status=401, error_type="authentication_error")

    try:
        body = await request.json()
    except Exception:
        return _error_response("invalid JSON body", status=400)
    if not isinstance(body, dict):
        return _error_response("body must be an object", status=400)

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _error_response("messages must be a non-empty array", status=400)

    model = body.get("model") or settings.gateway_default_model
    if not model:
        return _error_response(
            "model is required (no gateway default model configured)", status=400
        )

    stream = bool(body.get("stream"))
    new_user_turn = _is_new_user_turn(messages)

    session_id = await _resolve_session(state.working, principal, messages)

    payload_messages = messages
    try:
        prepared = await prepare_llm_messages(
            settings,
            state.facade,
            principal,
            messages,
            session_id=session_id,
            append_session=new_user_turn,
            enrich=new_user_turn,
            ccr_store=ccr_store_from_working(settings, state.working),
            caller_agent=principal.display if principal.type == "agent" else None,
        )
        payload_messages = prepared.messages
        session_id = prepared.session_id or session_id
    except Exception as exc:
        # Memory pipeline failures degrade to a plain proxy, never a 500.
        log.warning("gateway_prepare_failed", error=str(exc))

    upstream_body = {**body, "model": model, "messages": payload_messages}
    upstream_url = settings.gateway_upstream_base_url.rstrip("/") + "/chat/completions"
    timeout = httpx.Timeout(30.0, read=settings.gateway_upstream_timeout_seconds)

    if stream:
        return await _proxy_streaming(
            state, principal, session_id, upstream_url, upstream_body, timeout
        )
    return await _proxy_blocking(
        state, principal, session_id, upstream_url, upstream_body, timeout
    )


async def _proxy_blocking(
    state: ServerState,
    principal: Principal,
    session_id: str | None,
    url: str,
    body: dict[str, Any],
    timeout: httpx.Timeout,
) -> Response:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=_upstream_headers(state))
    except httpx.HTTPError as exc:
        log.warning("gateway_upstream_error", error=str(exc))
        METRICS.gateway_requests.inc(outcome="upstream_error")
        return _error_response(f"upstream error: {exc}", status=502, error_type="upstream_error")

    if resp.status_code == 200:
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            await _append_assistant_turn(
                state.facade, principal, session_id, extract_assistant_text(payload)
            )
        METRICS.gateway_requests.inc(outcome="ok")
    else:
        METRICS.gateway_requests.inc(outcome="upstream_status")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


async def _proxy_streaming(
    state: ServerState,
    principal: Principal,
    session_id: str | None,
    url: str,
    body: dict[str, Any],
    timeout: httpx.Timeout,
) -> Response:
    client = httpx.AsyncClient(timeout=timeout)
    try:
        upstream = client.stream("POST", url, json=body, headers=_upstream_headers(state))
        resp = await upstream.__aenter__()
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("gateway_upstream_error", error=str(exc))
        METRICS.gateway_requests.inc(outcome="upstream_error")
        return _error_response(f"upstream error: {exc}", status=502, error_type="upstream_error")

    if resp.status_code != 200:
        content = await resp.aread()
        media_type = resp.headers.get("content-type", "application/json")
        await upstream.__aexit__(None, None, None)
        await client.aclose()
        METRICS.gateway_requests.inc(outcome="upstream_status")
        return Response(content=content, status_code=resp.status_code, media_type=media_type)

    accumulator = _StreamAccumulator()

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes():
                accumulator.feed(chunk)
                yield chunk
        finally:
            await upstream.__aexit__(None, None, None)
            await client.aclose()
            await _append_assistant_turn(
                state.facade, principal, session_id, accumulator.text()
            )
            METRICS.gateway_requests.inc(outcome="ok_stream")

    return StreamingResponse(
        relay(),
        media_type=resp.headers.get("content-type", "text/event-stream"),
        headers={"Cache-Control": "no-cache"},
    )
