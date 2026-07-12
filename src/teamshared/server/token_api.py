"""HTTP handler for self-service bearer token minting."""

from __future__ import annotations

import re
import secrets
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from teamshared.clients.agent_setup import (
    KNOWN_AGENT_TYPES,
    canonical_install_script_url,
    normalize_agent_type,
)
from teamshared.config import Settings
from teamshared.identity.agent_tokens import AgentTokenMinter
from teamshared.invite import InviteStore
from teamshared.logging import get_logger
from teamshared.metrics import METRICS

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


async def _mint_token(agent: str, minter: AgentTokenMinter) -> JSONResponse:
    agent_type, token = await minter.mint(agent)
    log.info("token_minted", agent=agent_type, token_prefix=token[:12])
    return JSONResponse({"agent": agent_type, "token": token, "token_type": "tsk"})


async def _redeem_invite_for_token(
    invite_code: str,
    agent_hint: str | None,
    *,
    settings: Settings,
    minter: AgentTokenMinter,
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
    agent_type, token = await minter.mint(agent_type)
    log.info("token_minted_via_invite", agent=agent_type, token_prefix=token[:12])
    return agent_type, token


async def _mint_via_invite(
    invite_code: str,
    agent_hint: str | None,
    *,
    settings: Settings,
    minter: AgentTokenMinter,
    invites: InviteStore,
) -> JSONResponse:
    result = await _redeem_invite_for_token(
        invite_code,
        agent_hint,
        settings=settings,
        minter=minter,
        invites=invites,
    )
    if result[0] is None:
        return result[1]
    agent, token = result
    return JSONResponse({"agent": agent, "token": token, "token_type": "tsk"})


def invite_mint_path(invite: str, agent: str) -> str:
    """Path suffix for invite-based minting (``/tokens/mint/{invite}/{agent}``)."""
    return f"/tokens/mint/{invite}/{agent}"


_LANDING_CSS = """
    :root {
      --bg: #07080d;
      --bg-soft: #0d0f17;
      --panel: #11131d;
      --border: rgba(255,255,255,0.08);
      --text: #f4f5fb;
      --muted: #9aa0b4;
      --indigo: #6366f1;
      --indigo-bright: #818cf8;
      --max: 1120px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }
    a { color: inherit; text-decoration: none; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    h1, h2, h3 { letter-spacing: -0.02em; line-height: 1.1; margin: 0; }
    p { margin: 0; }

    .brand { display: inline-flex; align-items: center; gap: .55rem; font-weight: 700; font-size: 1.05rem; color: #fff; }
    .brand-mark { width: 1.4rem; height: 1.4rem; border-radius: 6px;
      background: url("/assets/logo.png") center/contain no-repeat; }

    .btn { display: inline-flex; align-items: center; justify-content: center; font-weight: 600;
      border-radius: 10px; padding: .6rem 1.05rem; font-size: .92rem; transition: transform .12s ease, background .15s ease, border-color .15s ease; border: 1px solid transparent; cursor: pointer; }
    .btn:hover { transform: translateY(-1px); }
    .btn-primary { background: var(--indigo); color: #fff; box-shadow: 0 8px 24px -8px rgba(99,102,241,.8); }
    .btn-primary:hover { background: var(--indigo-bright); }
    .btn-ghost { background: rgba(255,255,255,.04); color: #fff; border-color: var(--border); }
    .btn-ghost:hover { background: rgba(255,255,255,.08); }
    .btn-lg { padding: .8rem 1.4rem; font-size: 1rem; }
    .link { color: var(--muted); font-weight: 500; font-size: .92rem; }
    .link:hover { color: #fff; }

    .nav { position: sticky; top: 0; z-index: 20; backdrop-filter: saturate(160%) blur(12px);
      background: rgba(7,8,13,.72); border-bottom: 1px solid var(--border); }
    .nav-inner { max-width: var(--max); margin: 0 auto; padding: .85rem 1.5rem; display: flex; align-items: center; gap: 1.5rem; }
    .nav-links { display: flex; gap: 1.5rem; margin-left: 1rem; }
    .nav-links a { color: var(--muted); font-size: .92rem; font-weight: 500; }
    .nav-links a:hover { color: #fff; }
    .nav-cta { margin-left: auto; display: flex; align-items: center; gap: 1rem; }

    .hero { position: relative; overflow: hidden; padding: 6.5rem 1.5rem 5rem; text-align: center; }
    .hero-glow { position: absolute; inset: -30% 0 auto 0; height: 720px; pointer-events: none;
      background:
        radial-gradient(600px 380px at 50% 0%, rgba(99,102,241,.35), transparent 70%),
        radial-gradient(500px 320px at 15% 10%, rgba(129,140,248,.18), transparent 70%),
        radial-gradient(500px 320px at 85% 5%, rgba(56,189,248,.14), transparent 70%); }
    .hero-inner { position: relative; max-width: 840px; margin: 0 auto; }
    .eyebrow { display: inline-flex; align-items: center; gap: .5rem; padding: .35rem .85rem; border-radius: 999px;
      border: 1px solid var(--border); background: rgba(255,255,255,.04); color: var(--muted);
      font-size: .82rem; font-weight: 500; margin-bottom: 1.6rem; }
    .eyebrow:hover { color: #fff; border-color: rgba(129,140,248,.5); }
    .hero h1 { font-size: clamp(2.4rem, 6vw, 4rem); font-weight: 800;
      background: linear-gradient(180deg, #fff 35%, #b8bce0); -webkit-background-clip: text;
      background-clip: text; -webkit-text-fill-color: transparent; }
    .lede { max-width: 640px; margin: 1.4rem auto 0; color: var(--muted); font-size: 1.12rem; }
    .hero-actions { display: flex; gap: .8rem; justify-content: center; flex-wrap: wrap; margin-top: 2.2rem; }
    .hero-install { display: inline-flex; align-items: center; gap: .6rem; margin-top: 2.2rem;
      background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: .65rem 1rem;
      font-size: .9rem; color: #d7dae6; }
    .hero-install .prompt { color: var(--indigo-bright); font-family: ui-monospace, monospace; }
    .hero-foot { margin-top: 1.4rem; color: var(--muted); font-size: .88rem; }

    .strip { max-width: var(--max); margin: 0 auto; padding: 2rem 1.5rem 3rem; text-align: center; }
    .strip-label { display: block; color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .12em; }
    .strip-logos { margin-top: .9rem; color: #c7cad6; font-weight: 600; font-size: 1.05rem; opacity: .8; }

    .section { max-width: var(--max); margin: 0 auto; padding: 4.5rem 1.5rem; }
    .section-alt { background: var(--bg-soft); max-width: none; }
    .section-alt > .section-head, .section-alt > .grid { max-width: var(--max); margin-left: auto; margin-right: auto; }
    .section-head { max-width: 620px; margin: 0 auto 2.8rem; text-align: center; }
    .section-head h2 { font-size: clamp(1.8rem, 3.5vw, 2.5rem); font-weight: 800; }
    .section-head p { color: var(--muted); margin-top: .9rem; font-size: 1.05rem; }

    .grid { display: grid; gap: 1.1rem; }
    .grid-5 { grid-template-columns: repeat(5, 1fr); }
    .grid-4 { grid-template-columns: repeat(4, 1fr); }
    .grid-3 { grid-template-columns: repeat(3, 1fr); }

    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 1.6rem 1.4rem;
      transition: border-color .15s ease, transform .15s ease; }
    .card:hover { border-color: rgba(129,140,248,.45); transform: translateY(-3px); }
    .card-icon { width: 2.4rem; height: 2.4rem; border-radius: 10px; display: grid; place-items: center;
      font-size: 1.25rem; color: var(--indigo-bright); background: rgba(99,102,241,.12);
      border: 1px solid rgba(99,102,241,.25); margin-bottom: 1rem; }
    .card h3 { font-size: 1.15rem; margin-bottom: .5rem; }
    .card p { color: var(--muted); font-size: .94rem; }

    .steps .step { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 1.7rem 1.5rem; }
    .step-n { display: inline-grid; place-items: center; width: 2rem; height: 2rem; border-radius: 8px;
      background: var(--indigo); color: #fff; font-weight: 700; margin-bottom: 1rem; }
    .step h3 { font-size: 1.15rem; margin-bottom: .5rem; }
    .step p { color: var(--muted); font-size: .94rem; }
    .step code, .card code { background: rgba(255,255,255,.06); border-radius: 5px; padding: .05rem .35rem;
      font-size: .85em; color: var(--indigo-bright); }

    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; align-items: center; }
    .kicker { display: inline-block; color: var(--indigo-bright); font-weight: 600; font-size: .82rem;
      text-transform: uppercase; letter-spacing: .1em; margin-bottom: .9rem; }
    .split-copy h2 { font-size: clamp(1.7rem, 3vw, 2.3rem); font-weight: 800; }
    .split-copy > p { color: var(--muted); margin-top: 1rem; font-size: 1.05rem; }
    .checks { list-style: none; padding: 0; margin: 1.5rem 0 0; display: grid; gap: .7rem; }
    .checks li { position: relative; padding-left: 1.8rem; color: #d7dae6; font-size: .96rem; }
    .checks li::before { content: "✓"; position: absolute; left: 0; top: 0; color: var(--indigo-bright);
      font-weight: 700; }
    .split-actions { display: flex; align-items: center; gap: 1.2rem; margin-top: 1.8rem; flex-wrap: wrap; }

    .window { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; overflow: hidden;
      box-shadow: 0 30px 80px -40px rgba(99,102,241,.6); }
    .window-bar { display: flex; gap: .4rem; padding: .8rem 1rem; border-bottom: 1px solid var(--border); background: rgba(255,255,255,.02); }
    .window-bar span { width: .7rem; height: .7rem; border-radius: 50%; background: #2c3042; }
    .window-body { padding: 1.1rem 1.2rem; display: grid; gap: .7rem; }
    .wrow { font-size: .88rem; color: #d7dae6; display: flex; align-items: center; gap: .6rem; }
    .wrow.muted { color: var(--muted); font-family: ui-monospace, monospace; font-size: .82rem; margin-top: .3rem; }
    .pill { font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
      padding: .15rem .5rem; border-radius: 999px; }
    .pill-sem { background: rgba(99,102,241,.18); color: #a5b4fc; }
    .pill-epi { background: rgba(56,189,248,.16); color: #7dd3fc; }
    .pill-proc { background: rgba(167,139,250,.16); color: #c4b5fd; }

    .cta-band { padding: 5rem 1.5rem; text-align: center; }
    .cta-inner { max-width: 640px; margin: 0 auto; padding: 3rem 2rem; border-radius: 24px;
      border: 1px solid var(--border);
      background: radial-gradient(120% 140% at 50% 0%, rgba(99,102,241,.22), transparent 60%), var(--panel); }
    .cta-inner h2 { font-size: clamp(1.8rem, 3.5vw, 2.5rem); font-weight: 800; }
    .cta-inner p { color: var(--muted); margin-top: 1rem; font-size: 1.05rem; }

    .footer { border-top: 1px solid var(--border); background: var(--bg-soft); }
    .footer-inner { max-width: var(--max); margin: 0 auto; padding: 2.2rem 1.5rem; display: flex;
      align-items: center; gap: 1.2rem; flex-wrap: wrap; }
    .footer-tag { color: var(--muted); font-size: .9rem; }
    .footer-links { margin-left: auto; display: flex; gap: 1.3rem; flex-wrap: wrap; }
    .footer-links a { color: var(--muted); font-size: .9rem; }
    .footer-links a:hover { color: #fff; }

    @media (max-width: 900px) {
      .grid-5 { grid-template-columns: repeat(2, 1fr); }
      .grid-4 { grid-template-columns: repeat(2, 1fr); }
      .grid-3 { grid-template-columns: 1fr; }
      .split { grid-template-columns: 1fr; gap: 2rem; }
    }
    @media (max-width: 640px) {
      .nav-links { display: none; }
      .grid-5 { grid-template-columns: 1fr; }
      .grid-4 { grid-template-columns: 1fr; }
      .hero { padding-top: 4.5rem; }
      .hero-install { max-width: 100%; overflow-x: auto; }
    }
"""


def _service_banner_json() -> JSONResponse:
    return JSONResponse(
        {
            "service": "teamshared",
            "mcp": "/mcp",
            "health": "/health",
            "memory_dashboard": "/memory",
            "state": "/state",
            "tokens_mint": "/tokens/mint",
            "tokens_invites": "/tokens/invites",
            "token_via_invite": "/?invite=<code>&agent=<name>",
            "install": "/install",
            "install_script": "/install.sh",
            "plugin_bundle": "/install/plugin/teamshared.tar.gz",
        }
    )


def _landing_page_html() -> str:
    agents = ", ".join(a.capitalize() for a in sorted(KNOWN_AGENT_TYPES))
    install_cmd = f"curl -fsSL {canonical_install_script_url()} | bash"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="/favicon.ico" sizes="any" />
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/favicon-32.png" />
  <link rel="icon" type="image/png" sizes="16x16" href="/assets/favicon-16.png" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <title>TeamShared — Shared context for your agentic workforce</title>
  <meta name="description" content="Multi-pillar agent memory, exposed as an MCP server. Give Cursor, Codex, Claude, and every agent on your team one durable, shared memory." />
  <style>{_LANDING_CSS}</style>
</head>
<body>
  <header class="nav">
    <div class="nav-inner">
      <a class="brand" href="/">
        <span class="brand-mark" aria-hidden="true"></span>
        TeamShared
      </a>
      <nav class="nav-links">
        <a href="#pillars">Memory</a>
        <a href="#how">How it works</a>
        <a href="#console">Console</a>
      </nav>
      <div class="nav-cta">
        <a class="link" href="/login">Sign in</a>
        <a class="btn btn-primary" href="/login">Start free</a>
      </div>
    </div>
  </header>

  <main>
    <section class="hero">
      <div class="hero-glow" aria-hidden="true"></div>
      <div class="hero-inner">
        <a class="eyebrow" href="#pillars">Multi-pillar agent memory · MCP-native</a>
        <h1>Shared context for your agentic workforce.</h1>
        <p class="lede">
          TeamShared gives Cursor, Codex, Claude, and every other agent that speaks MCP
          a single durable memory — the facts, decisions, and playbooks your team builds
          stay learned across sessions, repos, and teammates.
        </p>
        <div class="hero-actions">
          <a class="btn btn-primary btn-lg" href="/login">Create your free account</a>
          <a class="btn btn-ghost btn-lg" href="/install">Install an agent</a>
        </div>
        <div class="hero-install">
          <span class="prompt">$</span>
          <code>{install_cmd}</code>
        </div>
        <p class="hero-foot">Free to start · no credit card · sign in with just your email.</p>
      </div>
    </section>

    <section class="strip">
      <span class="strip-label">Works with the agents you already use</span>
      <div class="strip-logos">{agents}</div>
    </section>

    <section id="pillars" class="section">
      <div class="section-head">
        <h2>Memory with structure, not logs.</h2>
        <p>Five pillars keep context organized so recall stays sharp as your team's
        knowledge grows.</p>
      </div>
      <div class="grid grid-5">
        <article class="card">
          <div class="card-icon">◷</div>
          <h3>Working</h3>
          <p>A fast, Redis-backed buffer for the current task. Per-session by default,
          distilled into durable memory when it matters.</p>
        </article>
        <article class="card">
          <div class="card-icon">◆</div>
          <h3>Semantic</h3>
          <p>Stable facts, preferences, and knowledge — the things that should still be
          true next week, searchable by meaning.</p>
        </article>
        <article class="card">
          <div class="card-icon">◔</div>
          <h3>Episodic</h3>
          <p>A distilled timeline of past sessions and events, so agents remember what
          the team did and why.</p>
        </article>
        <article class="card">
          <div class="card-icon">▤</div>
          <h3>Procedural</h3>
          <p>Versioned, how-to playbooks agents can read and follow — your team's best
          workflows, encoded.</p>
        </article>
        <article class="card">
          <div class="card-icon">◎</div>
          <h3>Strategic</h3>
          <p>Vision, mission, and OKRs that keep agents aligned to where the team is
          headed — long-horizon goals, not just facts.</p>
        </article>
      </div>
    </section>

    <section id="how" class="section section-alt">
      <div class="section-head">
        <h2>How it works</h2>
        <p>Connect in one command. Your agents do the rest.</p>
      </div>
      <div class="grid grid-3 steps">
        <article class="step">
          <span class="step-n">1</span>
          <h3>Connect over MCP</h3>
          <p>Point any MCP client at <code>/mcp</code> with a bearer token. One install
          script wires up {agents} and more.</p>
        </article>
        <article class="step">
          <span class="step-n">2</span>
          <h3>Recall before acting</h3>
          <p>Agents call <code>memory_recall</code> early in a task to pull relevant
          facts, episodes, and playbooks — grounded in your team's real history.</p>
        </article>
        <article class="step">
          <span class="step-n">3</span>
          <h3>Remember what matters</h3>
          <p>A call to <code>memory_remember</code> persists durable knowledge that every
          teammate's agent can read by default. Working memory stays private.</p>
        </article>
      </div>
    </section>

    <section id="console" class="section">
      <div class="split">
        <div class="split-copy">
          <span class="kicker">For humans</span>
          <h2>A console for the people behind the agents.</h2>
          <p>The team console is a server-rendered web app for browsing and curating the
          brain — no API client required. Sign in with your email and a one-time code.</p>
          <ul class="checks">
            <li>Memory wiki — facts, episodes, and playbooks as a living knowledge base.</li>
            <li>Memory explorer — search and inspect records across every pillar.</li>
            <li>Agents &amp; keys — add agents, mint and revoke API keys.</li>
            <li>Approvals — review captured memory before it goes live.</li>
          </ul>
          <div class="split-actions">
            <a class="btn btn-primary" href="/login">Open the console</a>
          </div>
        </div>
        <div class="split-visual" aria-hidden="true">
          <div class="window">
            <div class="window-bar"><span></span><span></span><span></span></div>
            <div class="window-body">
              <div class="wrow"><span class="pill pill-sem">semantic</span> Prefer pytest over unittest for new tests</div>
              <div class="wrow"><span class="pill pill-epi">episodic</span> Shipped multi-tenant orgs · 013_accounts.sql</div>
              <div class="wrow"><span class="pill pill-proc">procedural</span> ship-pr · v4</div>
              <div class="wrow"><span class="pill pill-sem">semantic</span> Prod host is teamshared.com</div>
              <div class="wrow muted">recall("how do we release?") → 8 hits</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="cta-band">
      <div class="cta-inner">
        <h2>Give your agents a memory worth sharing.</h2>
        <p>Create a free account in seconds — just your email. Your private brain is
        ready immediately.</p>
        <div class="hero-actions">
          <a class="btn btn-primary btn-lg" href="/login">Create your free account</a>
          <a class="btn btn-ghost btn-lg" href="/install">Install an agent</a>
        </div>
      </div>
    </section>
  </main>

  <footer class="footer">
    <div class="footer-inner">
      <span class="brand"><span class="brand-mark" aria-hidden="true"></span> TeamShared</span>
      <span class="footer-tag">Multi-pillar agent memory, exposed as an MCP server.</span>
      <nav class="footer-links">
        <a href="/login">Sign in</a>
        <a href="/install">Install</a>
        <a href="/health">Health</a>
      </nav>
    </div>
  </footer>
</body>
</html>"""


async def handle_root(
    request: Request,
    settings: Settings,
    minter: AgentTokenMinter,
    invites: InviteStore,
) -> Response:
    """Service banner, or mint a bearer token when ``?invite=&agent=`` are present."""
    invite_code = request.query_params.get("invite", "").strip()
    if invite_code:
        agent_hint = request.query_params.get("agent", "").strip() or None
        result = await _redeem_invite_for_token(
            invite_code,
            agent_hint,
            settings=settings,
            minter=minter,
            invites=invites,
        )
        if result[0] is None:
            return result[1]
        agent, token = result
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"agent": agent, "token": token, "token_type": "tsk"})
        return PlainTextResponse(token)

    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return _service_banner_json()

    return HTMLResponse(_landing_page_html())


async def handle_token_mint(
    request: Request,
    settings: Settings,
    minter: AgentTokenMinter,
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
        return await _mint_via_invite(
            path_invite,
            request.path_params.get("agent"),
            settings=settings,
            minter=minter,
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
        return await _mint_via_invite(
            invite_code,
            agent_str,
            settings=settings,
            minter=minter,
            invites=invites,
        )

    if not settings.mint_secret:
        return JSONResponse({"error": "invite_required"}, status_code=401)

    provided = request.headers.get(MINT_SECRET_HEADER, "").strip()
    if not provided or not secrets.compare_digest(provided, settings.mint_secret):
        METRICS.auth_rejected.inc(reason="invalid_mint_secret")
        log.warning("token_mint_rejected", reason="invalid_mint_secret")
        return JSONResponse({"error": "invalid_mint_secret"}, status_code=401)

    agent = _parse_agent(body.get("agent"))
    if agent is None:
        return JSONResponse({"error": "agent is required"}, status_code=400)
    return await _mint_token(agent, minter)


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
        METRICS.auth_rejected.inc(reason="invalid_mint_secret")
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



def invite_redeem_url(base_url: str, invite: str, agent: str) -> str:
    """Root URL query string for one-shot ``curl -fsS`` token mint."""
    root = base_url.rstrip("/")
    return f"{root}/?{urlencode({'invite': invite, 'agent': agent})}"


def invite_redeem_curl(base_url: str, invite: str, agent: str) -> str:
    return f"curl -fsS '{invite_redeem_url(base_url, invite, agent)}'"
