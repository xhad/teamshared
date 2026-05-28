"""HTTP handler for self-service bearer token minting."""

from __future__ import annotations

import re
import secrets
from html import escape

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from teamshared.auth import TokenStore
from teamshared.config import Settings
from teamshared.invite import InviteStore
from teamshared.logging import get_logger

log = get_logger(__name__)

MINT_SECRET_HEADER = "x-teamshared-mint-secret"
_AGENT_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")


def _parse_agent(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    agent = value.strip()
    if not _AGENT_PATTERN.fullmatch(agent):
        return None
    return agent


def _mint_enabled(settings: Settings) -> bool:
    return settings.mint_secret is not None or settings.self_service_tokens


def _mint_token(agent: str, store: TokenStore) -> JSONResponse:
    token = store.mint(agent)
    log.info("token_minted", agent=agent, token_prefix=token[:8])
    return JSONResponse({"agent": agent, "token": token})


def _mint_via_invite(
    invite_code: str,
    agent_hint: str | None,
    *,
    settings: Settings,
    store: TokenStore,
    invites: InviteStore,
) -> JSONResponse:
    if not settings.self_service_tokens:
        return JSONResponse({"error": "invite_disabled"}, status_code=404)
    code = invite_code.strip()
    if not code:
        return JSONResponse({"error": "invalid_invite"}, status_code=401)
    record = invites.get(code)
    if record is None:
        return JSONResponse({"error": "invalid_invite"}, status_code=401)
    agent = _parse_agent(agent_hint) if agent_hint else None
    if agent is None and record.agent:
        agent = _parse_agent(record.agent)
    if agent is None:
        return JSONResponse(
            {"error": "agent is required for this invite"},
            status_code=400,
        )
    if invites.redeem(code) is None:
        return JSONResponse({"error": "invalid_invite"}, status_code=401)
    return _mint_token(agent, store)


def invite_mint_path(invite: str, agent: str) -> str:
    """Path suffix for invite-based minting (``/tokens/mint/{invite}/{agent}``)."""
    return f"/tokens/mint/{invite}/{agent}"


def get_token_path(invite: str, agent: str | None = None) -> str:
    """Path for browser token redemption."""
    if agent:
        return f"/get-token/{invite}/{agent}"
    return f"/get-token/{invite}"


async def handle_token_mint(
    request: Request,
    settings: Settings,
    store: TokenStore,
    invites: InviteStore,
) -> JSONResponse:
    """Mint a bearer token.

    User path: ``POST /tokens/mint/{invite}/{agent}`` or JSON
    ``{"invite": "<code>", "agent": "cursor-chad"}``.
    Admin path: header ``X-Teamshared-Mint-Secret`` + ``{"agent": "cursor"}``.
    """
    if not _mint_enabled(settings):
        return JSONResponse({"error": "mint_disabled"}, status_code=404)

    path_invite = request.path_params.get("invite")
    if path_invite is not None:
        return _mint_via_invite(
            path_invite,
            request.path_params.get("agent"),
            settings=settings,
            store=store,
            invites=invites,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    invite_code = body.get("invite")
    if isinstance(invite_code, str) and invite_code.strip():
        agent_hint = body.get("agent")
        agent_str = agent_hint if isinstance(agent_hint, str) else None
        return _mint_via_invite(
            invite_code,
            agent_str,
            settings=settings,
            store=store,
            invites=invites,
        )

    if not settings.mint_secret:
        return JSONResponse({"error": "invite_required"}, status_code=401)

    provided = request.headers.get(MINT_SECRET_HEADER, "").strip()
    if not provided or not secrets.compare_digest(provided, settings.mint_secret):
        log.warning("token_mint_rejected", reason="invalid_mint_secret")
        return JSONResponse({"error": "invalid_mint_secret"}, status_code=401)

    agent = _parse_agent(body.get("agent"))
    if agent is None:
        return JSONResponse({"error": "agent is required"}, status_code=400)
    return _mint_token(agent, store)


async def handle_token_invite_create(
    request: Request,
    settings: Settings,
    invites: InviteStore,
) -> JSONResponse:
    """Create an invite code (admin: ``X-Teamshared-Mint-Secret``)."""
    if not settings.mint_secret:
        return JSONResponse({"error": "invite_create_disabled"}, status_code=404)

    provided = request.headers.get(MINT_SECRET_HEADER, "").strip()
    if not provided or not secrets.compare_digest(provided, settings.mint_secret):
        return JSONResponse({"error": "invalid_mint_secret"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        body = {}

    uses = body.get("uses", 1)
    if not isinstance(uses, int) or uses <= 0:
        return JSONResponse({"error": "uses must be a positive integer"}, status_code=400)

    agent = _parse_agent(body.get("agent")) if body.get("agent") is not None else None
    if body.get("agent") is not None and agent is None:
        return JSONResponse({"error": "invalid agent"}, status_code=400)

    record = invites.create(agent=agent, uses=uses)
    return JSONResponse(
        {
            "invite": record.code,
            "agent": record.agent,
            "uses_left": record.uses_left,
            "created_at": record.created_at,
        }
    )


async def handle_get_token_page(
    request: Request,
    settings: Settings,
    store: TokenStore,
    invites: InviteStore,
) -> Response:
    """Simple browser page for redeeming an invite code."""
    if not settings.self_service_tokens:
        return HTMLResponse("<h1>Token self-service is disabled</h1>", status_code=404)

    invite_code = (
        request.path_params.get("invite")
        or request.query_params.get("invite", "")
    ).strip()
    agent = (
        request.path_params.get("agent")
        or request.query_params.get("agent", "")
    ).strip()
    error = ""

    if invite_code:
        parsed_agent = _parse_agent(agent) if agent else None
        record = invites.get(invite_code)
        if record is None:
            error = "Invalid or expired invite code."
        else:
            final_agent = parsed_agent or (
                _parse_agent(record.agent) if record.agent else None
            )
            if final_agent is None:
                error = "Enter your agent name below (e.g. cursor-chad)."
            elif invites.redeem(invite_code) is None:
                error = "Invalid or expired invite code."
            else:
                token = store.mint(final_agent)
                log.info("token_minted_via_web", agent=final_agent, token_prefix=token[:8])
                base = str(request.base_url).rstrip("/")
                return HTMLResponse(
                    _token_result_html(final_agent, token, base),
                    status_code=200,
                )

    return HTMLResponse(_token_form_html(error=error, invite=invite_code, agent=agent))


def _token_form_html(*, error: str, invite: str, agent: str) -> str:
    err = f"<p style='color:#b00020'>{escape(error)}</p>" if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>teamshared token</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; }}
    label {{ display: block; margin-top: 1rem; font-weight: 600; }}
    input {{ width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.6rem 1rem; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>Get your teamshared token</h1>
  <p>Paste the invite code from your admin, choose a unique agent name, and submit.</p>
  {err}
  <form method="get" action="/get-token">
    <label for="invite">Invite code</label>
    <input id="invite" name="invite" required value="{escape(invite)}" />
    <label for="agent">Agent name (e.g. cursor-chad)</label>
    <input id="agent" name="agent" required placeholder="cursor-yourname" value="{escape(agent)}" />
    <button type="submit">Create token</button>
  </form>
</body>
</html>"""


def _token_result_html(agent: str, token: str, base_url: str) -> str:
    mcp_url = f"{base_url}/mcp"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>teamshared token</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; }}
    code, pre {{ word-break: break-all; background: #f4f4f5; padding: 0.75rem; display: block; }}
  </style>
</head>
<body>
  <h1>Your teamshared token</h1>
  <p><strong>Agent:</strong> {escape(agent)}</p>
  <p>Copy this token now. It is shown once.</p>
  <pre id="token">{escape(token)}</pre>
  <p>Set in your shell or MCP config:</p>
  <pre>export TEAMSHARED_URL={escape(mcp_url)}
export TEAMSHARED_TOKEN={escape(token)}</pre>
</body>
</html>"""


def invite_redeem_curl(base_url: str, invite: str, agent: str) -> str:
    root = base_url.rstrip("/")
    return f"curl -fsS -X POST '{root}{invite_mint_path(invite, agent)}'"
