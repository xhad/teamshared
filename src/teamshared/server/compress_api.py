"""HTTP handler for POST /compress (bearer-authenticated)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from teamshared.auth import current_principal
from teamshared.compress.ccr_store import org_scope_from_id
from teamshared.compress.engine import compress_messages_with_ccr
from teamshared.compress.factory import ccr_store_from_working
from teamshared.server.state import get_state


async def handle_compress(request: Request) -> JSONResponse:
    """Compress a chat message list before forwarding to an LLM."""
    principal = current_principal()
    if principal is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"error": "messages must be a non-empty list"}, status_code=400)

    state = get_state()
    store = ccr_store_from_working(state.settings, state.working)
    result = await compress_messages_with_ccr(
        state.settings,
        messages,
        org_scope=org_scope_from_id(principal.org_id),
        store=store,
    )
    return JSONResponse(
        {
            "messages": result.messages,
            "compressed": result.compressed,
            "stats": {
                "original_chars": result.stats.original_chars,
                "compressed_chars": result.stats.compressed_chars,
                "chars_saved": result.stats.chars_saved,
                "ratio": result.stats.ratio,
                "messages_touched": result.stats.messages_touched,
                "refs": result.stats.refs,
            },
        }
    )


async def handle_compress_retrieve(request: Request) -> JSONResponse:
    """Retrieve a CCR original by ref."""
    principal = current_principal()
    if principal is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    ref = request.query_params.get("ref")
    if not ref:
        return JSONResponse({"error": "ref query parameter required"}, status_code=400)

    state = get_state()
    store = ccr_store_from_working(state.settings, state.working)
    content = await store.get(org_scope_from_id(principal.org_id), ref)
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ref": ref, "content": content})
