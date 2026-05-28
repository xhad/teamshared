"""HTTP handler for self-service bearer token minting."""

from __future__ import annotations

import re
import secrets
from html import escape

from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from teamshared.auth import TokenStore
from teamshared.clients.agent_setup import (
    KNOWN_AGENT_TYPES,
    agent_setup,
    normalize_agent_type,
)
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


def _resolve_invite_agent_type(
    agent_hint: str | None,
    invite_agent: str | None,
) -> str | None:
    for candidate in (agent_hint, invite_agent):
        if not candidate:
            continue
        agent_type = normalize_agent_type(candidate)
        if agent_type is not None:
            return agent_type
    return None


def _invalid_agent_type_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "agent must be a known type",
            "allowed": sorted(KNOWN_AGENT_TYPES),
        },
        status_code=400,
    )


def _mint_enabled(settings: Settings) -> bool:
    return settings.mint_secret is not None or settings.self_service_tokens


def _mint_token(agent: str, store: TokenStore) -> JSONResponse:
    token = store.mint(agent)
    log.info("token_minted", agent=agent, token_prefix=token[:8])
    return JSONResponse({"agent": agent, "token": token})


def _redeem_invite_for_token(
    invite_code: str,
    agent_hint: str | None,
    *,
    settings: Settings,
    store: TokenStore,
    invites: InviteStore,
) -> tuple[str, str] | tuple[None, JSONResponse]:
    """Return ``(agent, token)`` or ``(None, error_response)``."""
    if not settings.self_service_tokens:
        return None, JSONResponse({"error": "invite_disabled"}, status_code=404)
    code = invite_code.strip()
    if not code:
        return None, JSONResponse({"error": "invalid_invite"}, status_code=401)
    record = invites.get(code)
    if record is None:
        return None, JSONResponse({"error": "invalid_invite"}, status_code=401)
    agent_type = _resolve_invite_agent_type(agent_hint, record.agent)
    if agent_type is None:
        if agent_hint or record.agent:
            return None, _invalid_agent_type_response()
        return None, JSONResponse(
            {"error": "agent is required for this invite", "allowed": sorted(KNOWN_AGENT_TYPES)},
            status_code=400,
        )
    if invites.redeem(code) is None:
        return None, JSONResponse({"error": "invalid_invite"}, status_code=401)
    token = store.mint(agent_type)
    log.info("token_minted_via_invite", agent=agent_type, token_prefix=token[:8])
    return agent_type, token


def _mint_via_invite(
    invite_code: str,
    agent_hint: str | None,
    *,
    settings: Settings,
    store: TokenStore,
    invites: InviteStore,
) -> JSONResponse:
    result = _redeem_invite_for_token(
        invite_code,
        agent_hint,
        settings=settings,
        store=store,
        invites=invites,
    )
    if result[0] is None:
        return result[1]
    agent, token = result
    return JSONResponse({"agent": agent, "token": token})


def invite_mint_path(invite: str, agent: str) -> str:
    """Path suffix for invite-based minting (``/tokens/mint/{invite}/{agent}``)."""
    return f"/tokens/mint/{invite}/{agent}"


def get_token_path(invite: str, agent: str | None = None) -> str:
    """Path for browser token redemption."""
    if agent:
        return f"/get-token/{invite}/{agent}"
    return f"/get-token/{invite}"


async def handle_root(
    request: Request,
    settings: Settings,
    store: TokenStore,
    invites: InviteStore,
) -> Response:
    """Service banner, or mint a bearer token when ``?invite=&agent=`` are present."""
    invite_code = request.query_params.get("invite", "").strip()
    if invite_code:
        agent_hint = request.query_params.get("agent", "").strip() or None
        result = _redeem_invite_for_token(
            invite_code,
            agent_hint,
            settings=settings,
            store=store,
            invites=invites,
        )
        if result[0] is None:
            return result[1]
        agent, token = result
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"agent": agent, "token": token})
        return PlainTextResponse(token)

    return JSONResponse(
        {
            "service": "teamshared-memory",
            "mcp": "/mcp",
            "health": "/health",
            "state": "/state",
            "get_token": "/get-token",
            "tokens_mint": "/tokens/mint",
            "tokens_invites": "/tokens/invites",
            "token_via_invite": "/?invite=<code>&agent=<name>",
        }
    )


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

    agent = None
    if body.get("agent") is not None:
        agent_type = normalize_agent_type(str(body.get("agent")))
        if agent_type is None:
            return _invalid_agent_type_response()
        agent = agent_type

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
    record = invites.get(invite_code) if invite_code else None
    preset_type = normalize_agent_type(record.agent) if record and record.agent else None
    agent = (
        request.path_params.get("agent")
        or request.query_params.get("agent", "")
    ).strip()
    if not agent and preset_type:
        agent = preset_type
    error = ""

    if invite_code:
        if record is None:
            error = "Invalid or expired invite code."
        else:
            agent_type = _resolve_invite_agent_type(agent or None, record.agent)
            if agent_type is None:
                if agent or record.agent:
                    error = f"Agent must be one of: {', '.join(sorted(KNOWN_AGENT_TYPES))}."
                else:
                    error = "Choose your agent type below."
            elif invites.redeem(invite_code) is None:
                error = "Invalid or expired invite code."
            else:
                token = store.mint(agent_type)
                log.info("token_minted_via_web", agent=agent_type, token_prefix=token[:8])
                base = str(request.base_url).rstrip("/")
                return HTMLResponse(
                    _token_result_html(agent_type, token, base),
                    status_code=200,
                )

    return HTMLResponse(
        _token_form_html(error=error, invite=invite_code, agent=agent, preset_type=preset_type)
    )


def _token_form_html(
    *,
    error: str,
    invite: str,
    agent: str,
    preset_type: str | None = None,
) -> str:
    err = f"<p style='color:#b00020'>{escape(error)}</p>" if error else ""
    allowed = ", ".join(sorted(KNOWN_AGENT_TYPES))
    agent_value = preset_type or agent
    readonly = " readonly" if preset_type else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>teamshared token</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 3rem auto; padding: 0 1rem; }}
    label {{ display: block; margin-top: 1rem; font-weight: 600; }}
    input {{ width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.6rem 1rem; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>Get your teamshared token</h1>
  <p>Paste the invite code from your admin and pick your agent type ({allowed}).</p>
  {err}
  <form method="get" action="/get-token">
    <label for="invite">Invite code</label>
    <input id="invite" name="invite" required value="{escape(invite)}" />
    <label for="agent">Agent type</label>
    <input id="agent" name="agent" required placeholder="cursor" value="{escape(agent_value)}"{readonly} />
    <button type="submit">Create token</button>
  </form>
</body>
</html>"""


def _token_result_html(agent_type: str, token: str, base_url: str) -> str:
    mcp_url = f"{base_url}/mcp"
    setup = agent_setup(agent_type, mcp_url=mcp_url, token=token)
    if setup is None:
        return f"""<!doctype html>
<html lang="en"><body><pre>{escape(token)}</pre></body></html>"""

    steps_html = "".join(f"<li>{escape(step)}</li>" for step in setup.steps)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>teamshared setup — {escape(setup.title)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    pre {{ word-break: break-all; background: #f4f4f5; padding: 0.75rem; overflow-x: auto; font-size: 0.9rem; }}
    ol {{ padding-left: 1.25rem; }}
    .path {{ color: #555; font-size: 0.95rem; }}
  </style>
</head>
<body>
  <h1>Connect teamshared to {escape(setup.title)}</h1>
  <p>Your bearer token is embedded in the config below. It is shown once — copy it now if you need it elsewhere.</p>
  <p class="path"><strong>Config file:</strong> <code>{escape(setup.config_path)}</code></p>
  <ol>{steps_html}</ol>
  <pre>{escape(setup.snippet)}</pre>
  <p><strong>Token only:</strong></p>
  <pre>{escape(token)}</pre>
</body>
</html>"""


def invite_redeem_url(base_url: str, invite: str, agent: str) -> str:
    """Root URL query string for one-shot ``curl -fsS`` token mint."""
    root = base_url.rstrip("/")
    return f"{root}/?{urlencode({'invite': invite, 'agent': agent})}"


def invite_redeem_curl(base_url: str, invite: str, agent: str) -> str:
    return f"curl -fsS '{invite_redeem_url(base_url, invite, agent)}'"
