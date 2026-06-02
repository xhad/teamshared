"""FastMCP app factory + ASGI assembly for HTTP transport.

For HTTP we wrap FastMCP's streamable-HTTP ASGI app in a Starlette host that
adds:

- ``/health`` -- unauthenticated liveness probe.
- ``BearerAuthMiddleware`` -- per-agent token validation in front of ``/mcp``.

For stdio we just return the configured ``FastMCP`` instance and let the
caller invoke ``mcp.run(transport="stdio")``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from teamshared.auth import BearerAuthMiddleware, TokenStore
from teamshared.config import Settings, get_settings
from teamshared.config_validate import validate_settings
from teamshared.identity.agent_tokens import AgentTokenMinter
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.invite import InviteStore
from teamshared.logging import configure_logging, get_logger
from teamshared.memory.agent_state import AgentStateStore
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.graph import GraphStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.metrics import METRICS
from teamshared.server.api import build_api_app
from teamshared.server.capture import ToolCallCaptureMiddleware, ingest_turns
from teamshared.server.console import register_console_routes
from teamshared.server.dashboard import handle_memory_dashboard
from teamshared.server.health import check_components
from teamshared.server.install_api import (
    handle_install_asset,
    handle_install_index,
    handle_install_sh,
    handle_plugin_bundle,
    handle_uninstall_sh,
)
from teamshared.server.rate_limit import HttpRateLimitMiddleware, RateLimitLimits, RedisRateLimiter
from teamshared.server.services import ProductionServices, make_services
from teamshared.server.state import ServerState, clear_state, set_state
from teamshared.server.token_api import (
    handle_get_token_page,
    handle_root,
    handle_token_invite_create,
    handle_token_mint,
)
from teamshared.server.tools import register_tools
from teamshared.telemetry import instrument_asgi, setup_tracing

log = get_logger(__name__)


def build_mcp(settings: Settings | None = None) -> FastMCP:
    """Build a FastMCP instance with all teamshared tools registered."""
    settings = settings or get_settings()
    mcp: FastMCP = FastMCP(
        name="teamshared",
        instructions=(
            "Multi-pillar agent memory. Use `memory_recall` early in a task to "
            "pull relevant facts, episodes, and procedures. Use `memory_remember` "
            "to persist durable facts and `memory_session_*` for working memory."
        ),
    )
    register_tools(mcp)
    if settings.capture_enabled:
        mcp.add_middleware(
            ToolCallCaptureMiddleware(
                idle_seconds=settings.capture_idle_seconds,
                max_turns=settings.capture_max_turns,
            )
        )
    return mcp


async def _init_state(
    settings: Settings,
    services: ProductionServices,
    resolver: PrincipalResolver,
) -> ServerState:
    """Connect every backing store and assemble :class:`ServerState`."""
    tokens = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    # Single WorkingMemory instance, owned by services and shared with ServerState
    # (the console reaches it via services.working for sign-in OTP storage).
    working = services.working

    await working.connect()
    try:
        await services.tenant_db.connect()
    except Exception as exc:
        log.warning("tenant_db_connect_failed", error=str(exc))

    procedural = OrgProceduralStore(services.tenant_db)
    agent_state = AgentStateStore(working.client)
    audit = services.audit

    graph: GraphStore | None = GraphStore(
        settings.neo4j_url, settings.neo4j_user, settings.neo4j_password
    )
    try:
        await graph.connect()
    except Exception as exc:
        log.warning("graph_store_connect_failed", error=str(exc))
        graph = None

    facade = MemoryFacade(
        services=services,
        resolver=resolver,
        working=working,
        agent_state=agent_state,
        procedural=procedural,
        graph=graph,
    )

    state = ServerState(
        settings=settings,
        tokens=tokens,
        invites=invites,
        working=working,
        agent_state=agent_state,
        procedural=procedural,
        services=services,
        facade=facade,
        audit=audit,
        graph=graph,
        audit_db=services.tenant_db,
    )
    set_state(state)
    return state


async def _teardown_state(state: ServerState) -> None:
    await state.working.close()
    if state.graph is not None:
        await state.graph.close()
    await state.services.tenant_db.close()
    clear_state()


def build_http_app(settings: Settings | None = None) -> Starlette:
    """Build the public-facing Starlette ASGI app.

    Routes:
    - ``GET  /health``  -- unauthenticated probe.
    - ``GET  /memory``  -- public memory status dashboard (HTML).
    - ``GET  /``        -- landing page (HTML); JSON banner with ``Accept: application/json``;
                           mint via ``?invite=&agent=`` (plain text or JSON).
    - ``GET  /state``   -- bearer-scoped JSON state read (`repo`, `key` query params).
    - ``PUT  /state``   -- bearer-scoped JSON state write (`{repo, key, value}` body).
    - ``POST /sessions/turns`` -- bearer-scoped conversation-turn ingestion into capture session.
    - ``POST /tokens/mint`` -- mint a bearer token (invite code or admin secret).
    - ``POST /tokens/mint/{invite}/{agent}`` -- mint via invite (path params).
    - ``POST /tokens/invites`` -- create invite codes (admin secret).
    - ``GET  /get-token`` -- browser page to redeem an invite.
    - ``GET  /get-token/{invite}/{agent}`` -- browser redeem via path params.
    - ``GET  /login`` -- console magic-link sign-in (HTML); ``POST`` sends the link.
    - ``GET  /login/verify`` -- exchange a magic token for a ``ts_session`` cookie.
    - ``GET  /app`` -- signed-in web console (home overview); ``/app/*`` sections.
    - ``GET  /install`` -- install instructions (HTML).
    - ``GET  /install.sh`` -- unified installer (prompts for harness).
    - ``GET  /uninstall.sh`` -- unified uninstaller (prompts for harness).
    - ``GET  /install/assets/{path}`` -- harness config snippets (remote pull).
    - ``GET  /install/plugin/teamshared.tar.gz`` -- Cursor plugin bundle.
    - ``GET  /plugin/teamshared.tar.gz`` -- alias of the plugin bundle.
    - ``ANY  /mcp/*``   -- FastMCP streamable HTTP, gated by bearer auth.
    """
    settings = settings or get_settings()
    validate_settings(settings)
    configure_logging(settings.log_level)
    setup_tracing()

    mcp = build_mcp(settings)
    mcp_app = mcp.http_app(path="/")

    # Production services back both the /v1 REST surface and the converged MCP
    # tool surface (G2). Built eagerly (no I/O); the TenantDb pool is opened in
    # the lifespan below.
    services: ProductionServices = make_services(settings)
    resolver = PrincipalResolver(
        api_keys=services.api_keys,
        roles=services.roles,
        tenant_db=services.tenant_db,
        default_org_id=settings.default_org_id,
        session_secret=settings.session_secret,
    )
    api_app = None
    if settings.api_enabled:
        api_app = build_api_app(
            services,
            admin_secret=settings.api_admin_secret,
            session_secret=settings.session_secret,
        )

    async def health_route(request: Request) -> JSONResponse:
        try:
            from teamshared.server.state import get_state

            body = await check_components(get_state())
            return JSONResponse(body)
        except RuntimeError:
            return JSONResponse({"status": "starting"}, status_code=503)

    async def favicon_route(_: Request) -> Response:
        return Response(status_code=204)

    async def metrics_route(_: Request) -> Response:
        return Response(METRICS.render(), media_type="text/plain; version=0.0.4")

    async def memory_dashboard_route(request: Request) -> Response:
        try:
            from teamshared.server.state import get_state

            return await handle_memory_dashboard(request, get_state())
        except RuntimeError:
            return HTMLResponse(
                "<h1>teamshared</h1><p>Server is starting; memory dashboard not ready yet.</p>",
                status_code=503,
            )

    tokens = TokenStore(settings.tokens_file)
    invites = InviteStore(settings.invites_file)
    agent_minter = AgentTokenMinter(
        api_keys=services.api_keys,
        resolver=resolver,
        org_id=settings.default_org_id,
    )

    async def root_route(request: Request) -> Response:
        return await handle_root(request, settings, agent_minter, invites)

    async def token_mint_route(request: Request) -> JSONResponse:
        return await handle_token_mint(request, settings, agent_minter, invites)

    async def token_invite_create_route(request: Request) -> JSONResponse:
        return await handle_token_invite_create(request, settings, invites)

    async def get_token_route(request: Request) -> Response:
        return await handle_get_token_page(request, settings, agent_minter, invites)

    async def install_index_route(request: Request) -> HTMLResponse:
        return await handle_install_index(request)

    async def install_sh_route(request: Request) -> Response:
        return await handle_install_sh(request)

    async def uninstall_sh_route(request: Request) -> Response:
        return await handle_uninstall_sh(request)

    async def install_asset_route(request: Request) -> Response:
        return await handle_install_asset(request)

    async def plugin_bundle_route(request: Request) -> Response:
        return await handle_plugin_bundle(request)

    async def state_get_route(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo")
        key = request.query_params.get("key")
        if not repo or not key:
            return JSONResponse({"error": "repo and key query params are required"}, status_code=400)
        identity = request.state.agent
        principal = getattr(request.state, "principal", None)
        org = str(principal.org_id) if principal else str(settings.default_org_id)
        try:
            from teamshared.server.state import get_state

            value = await get_state().agent_state.get(identity.state_id, repo, key, org=org)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"repo": repo, "key": key, "value": value})

    async def state_put_route(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_json"}, status_code=400)
        repo = body.get("repo")
        key = body.get("key")
        value = body.get("value")
        if not isinstance(repo, str) or not isinstance(key, str):
            return JSONResponse({"error": "repo and key are required strings"}, status_code=400)
        if not isinstance(value, dict):
            return JSONResponse({"error": "value must be a JSON object"}, status_code=400)
        identity = request.state.agent
        principal = getattr(request.state, "principal", None)
        org = str(principal.org_id) if principal else str(settings.default_org_id)
        try:
            from teamshared.server.state import get_state

            await get_state().agent_state.set(identity.state_id, repo, key, value, org=org)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"repo": repo, "key": key, "stored": True})

    async def session_turns_route(request: Request) -> JSONResponse:
        """Append natural-language conversation turns to the caller's implicit
        per-agent capture session.

        Body: ``{"turns": [{"role": "user"|"assistant"|"tool"|"system",
        "content": "..."}]}``. This is the harness-agnostic conversation sink:
        a client-side adapter (e.g. the Cursor transcript hook) reads new turns
        from its harness transcript and POSTs them here. Turns share the same
        rolling session as the tool-call capture middleware.
        """
        if not settings.capture_enabled:
            return JSONResponse({"recorded": 0, "capture_disabled": True})
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_json"}, status_code=400)
        turns = body.get("turns")
        if not isinstance(turns, list) or not turns:
            return JSONResponse(
                {"error": "turns must be a non-empty array"}, status_code=400
            )
        identity = request.state.agent
        principal = getattr(request.state, "principal", None)
        org_id = principal.org_id if principal else settings.default_org_id
        from teamshared.server.state import get_state

        state = get_state()
        # Consent-first: raw conversation turns require an active grant whose
        # scope includes raw_turns. No grant -> 403, nothing recorded.
        if not await state.services.consent.capture_allowed(
            org_id, identity.agent, "raw_turns"
        ):
            METRICS.consent_denied_capture.inc(capability="raw_turns")
            return JSONResponse(
                {"recorded": 0, "consent_required": True}, status_code=403
            )
        recorded = await ingest_turns(
            state.working,
            org_id,
            identity.agent,
            turns,
            idle_seconds=settings.capture_idle_seconds,
            max_turns=settings.capture_max_turns,
        )
        return JSONResponse({"recorded": recorded})

    rate_limiter = RedisRateLimiter(
        settings.redis_url,
        enabled=settings.rate_limit_enabled,
        limits=RateLimitLimits(
            mint_per_minute=settings.rate_limit_mint_per_minute,
            otp_send_per_minute=settings.rate_limit_otp_send_per_minute,
            otp_verify_per_minute=settings.rate_limit_otp_verify_per_minute,
            mcp_per_minute=settings.rate_limit_mcp_per_minute,
        ),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await rate_limiter.connect()
        app.state.rate_limiter = rate_limiter
        state = await _init_state(settings, services, resolver)
        log.info("teamshared_server_started", host=settings.host, port=settings.port)
        async with mcp_app.lifespan(app):
            try:
                yield
            finally:
                log.info("teamshared_server_stopping")
                await _teardown_state(state)
                await rate_limiter.close()
                app.state.rate_limiter = None

    middleware = [
        Middleware(
            BearerAuthMiddleware,
            store=tokens,
            auth_disabled=settings.auth_disabled,
            resolver=resolver,
        ),
        Middleware(HttpRateLimitMiddleware),
    ]

    app = Starlette(
        routes=[
            Route("/", root_route, methods=["GET"]),
            Route("/favicon.ico", favicon_route, methods=["GET"]),
            Route("/health", health_route, methods=["GET"]),
            Route("/metrics", metrics_route, methods=["GET"]),
            Route("/memory", memory_dashboard_route, methods=["GET"]),
            Route("/get-token/{invite}/{agent}", get_token_route, methods=["GET"]),
            Route("/get-token/{invite}", get_token_route, methods=["GET"]),
            Route("/get-token", get_token_route, methods=["GET"]),
            Route("/install", install_index_route, methods=["GET"]),
            Route("/install.sh", install_sh_route, methods=["GET"]),
            Route("/uninstall.sh", uninstall_sh_route, methods=["GET"]),
            Route(
                "/install/assets/{asset_path:path}",
                install_asset_route,
                methods=["GET"],
            ),
            Route(
                "/install/plugin/teamshared.tar.gz",
                plugin_bundle_route,
                methods=["GET"],
            ),
            Route("/plugin/teamshared.tar.gz", plugin_bundle_route, methods=["GET"]),
            Route("/tokens/mint/{invite}/{agent}", token_mint_route, methods=["POST"]),
            Route("/tokens/mint", token_mint_route, methods=["POST"]),
            Route("/tokens/invites", token_invite_create_route, methods=["POST"]),
            Route("/state", state_get_route, methods=["GET"]),
            Route("/state", state_put_route, methods=["PUT"]),
            Route("/sessions/turns", session_turns_route, methods=["POST"]),
            *register_console_routes(settings, services),
            *([Mount("/v1", app=api_app)] if api_app is not None else []),
            Mount("/mcp", app=mcp_app),
        ],
        middleware=middleware,
        lifespan=lifespan,
    )
    instrument_asgi(app)
    return app
