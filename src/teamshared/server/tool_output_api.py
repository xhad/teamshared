"""HTTP handler for POST /tools/normalize (REST mirror of ``context_normalize``)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from teamshared.auth import current_principal
from teamshared.compress.ccr_store import org_scope_from_id
from teamshared.compress.factory import ccr_store_from_working
from teamshared.compress.tool_output import normalize_tool_output
from teamshared.server.state import get_state


async def handle_tool_normalize(request: Request) -> JSONResponse:
    """Strip, clean, and compress a tool output string."""
    principal = current_principal()
    if principal is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be an object"}, status_code=400)

    tool_name = body.get("tool_name")
    output = body.get("output")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return JSONResponse({"error": "tool_name required"}, status_code=400)
    if not isinstance(output, str) or not output.strip():
        return JSONResponse({"error": "output required"}, status_code=400)

    state = get_state()
    settings = state.settings
    store = ccr_store_from_working(settings, state.working)

    normalized = await normalize_tool_output(
        settings,
        tool_name.strip(),
        output,
        org_scope=org_scope_from_id(principal.org_id),
        store=store,
    )

    return JSONResponse(
        {
            "output": normalized.body,
            "compressed": normalized.compressed,
            "cleaned": normalized.cleaned,
            "stats": {
                "chars_saved": normalized.chars_saved,
                "ref": normalized.ref,
            },
        }
    )
