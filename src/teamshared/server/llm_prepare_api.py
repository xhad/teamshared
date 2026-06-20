"""Bearer-authenticated pre-LLM prepare endpoint (REST mirror of ``context_prepare``)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from teamshared.auth import current_principal
from teamshared.compress.context_prepare import run_context_prepare
from teamshared.server.state import get_state


async def handle_llm_prepare(request: Request) -> JSONResponse:
    """``POST /llm/prepare`` — session append → compress → enrich."""
    principal = current_principal()
    if principal is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    state = get_state()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be an object"}, status_code=400)

    messages = body.get("messages")
    prompt = body.get("prompt")
    session_id = body.get("session_id")
    repo = body.get("repo")
    github = body.get("github")
    append_session = body.get("append_session", True)
    enrich = body.get("enrich", True)
    token_budget = body.get("token_budget")

    try:
        result = await run_context_prepare(
            state.settings,
            state.facade,
            principal,
            state.working,
            messages=messages if isinstance(messages, list) else None,
            prompt=prompt if isinstance(prompt, str) else None,
            session_id=session_id if isinstance(session_id, str) else None,
            repo=repo if isinstance(repo, str) else None,
            github=github if isinstance(github, str) else None,
            append_session=bool(append_session),
            enrich=bool(enrich),
            token_budget=token_budget if isinstance(token_budget, int) else None,
        )
    except ValueError as exc:
        code = str(exc)
        status = 503 if code == "llm_prepare_disabled" else 400
        return JSONResponse({"error": code}, status_code=status)

    return JSONResponse(result)
