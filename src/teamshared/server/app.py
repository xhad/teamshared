"""FastMCP app factory + ASGI assembly for HTTP transport.

For HTTP we wrap FastMCP's streamable-HTTP ASGI app in a Starlette host that
adds:

- ``/health`` -- unauthenticated liveness probe.
- ``BearerAuthMiddleware`` -- per-agent token validation in front of ``/mcp``.

For stdio we just return the configured ``FastMCP`` instance and let the
caller invoke ``mcp.run(transport="stdio")``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from teamshared.auth import BearerAuthMiddleware
from teamshared.config import Settings, get_settings
from teamshared.config_validate import validate_settings
from teamshared.identity.agent_tokens import AgentTokenMinter
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.invite import InviteStore
from teamshared.logging import configure_logging, get_logger
from teamshared.memory.agent_state import AgentStateStore
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.graph import GraphStore
from teamshared.memory.graph_pg import PostgresGraphStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.skills import OrgSkillStore
from teamshared.memory.strategic import OrgStrategicStore
from teamshared.metrics import METRICS
from teamshared.server.api import build_api_app
from teamshared.server.capture import (
    MAX_TURNS_PER_REQUEST,
    ToolCallCaptureMiddleware,
    ingest_turns,
)
from teamshared.server.compress_api import handle_compress, handle_compress_retrieve
from teamshared.server.console import register_console_routes
from teamshared.server.console_csrf import ConsoleCsrfCookieMiddleware
from teamshared.server.dashboard import handle_memory_dashboard
from teamshared.server.gateway_api import (
    handle_gateway_chat_completions,
    handle_gateway_models,
)
from teamshared.server.health import check_components
from teamshared.server.idempotency import RedisIdempotencyGuard
from teamshared.server.install_api import (
    handle_install_asset,
    handle_install_index,
    handle_install_sh,
    handle_plugin_bundle,
    handle_uninstall_sh,
)
from teamshared.server.llm_prepare_api import handle_llm_prepare
from teamshared.server.mcp_output_middleware import ToolOutputNormalizeMiddleware
from teamshared.server.mcp_path import McpSlashMiddleware
from teamshared.server.shared_files_public import handle_shared_file_view
from teamshared.server.rate_limit import HttpRateLimitMiddleware, RateLimitLimits, RedisRateLimiter
from teamshared.server.services import ProductionServices, make_services
from teamshared.server.state import ServerState, clear_state, set_state
from teamshared.server.token_api import (
    handle_root,
    handle_token_invite_create,
    handle_token_mint,
)
from teamshared.server.tool_output_api import handle_tool_normalize
from teamshared.server.tools import register_tools
from teamshared.telemetry import instrument_asgi, setup_tracing

log = get_logger(__name__)

# Bundled brand assets (logo + favicons), shipped under the package and copied
# into the image by the Dockerfile (`COPY src ./src`).
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_CONTENT_TYPES = {
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
    ".css": "text/css",
    ".js": "text/javascript",
}


def _serve_static(name: str) -> Response:
    """Serve a file from the bundled static dir, guarding against traversal."""
    target = (_STATIC_DIR / name).resolve()
    if _STATIC_DIR not in target.parents or not target.is_file():
        return Response(status_code=404)
    media_type = _STATIC_CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(
        target,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


def build_mcp(settings: Settings | None = None) -> FastMCP:
    """Build a FastMCP instance with all teamshared tools registered."""
    settings = settings or get_settings()
    mcp: FastMCP = FastMCP(
        name="teamshared",
        instructions=(
            "Multi-pillar agent memory. Before non-trivial work: `memory_recall` "
            "with durable scope (default excludes working), repo/github slugs, "
            "and a short keyword anchor in query. Use `memory_think` for "
            "synthesis after recall finds hits. Store facts with "
            "`memory_remember`; store atomic how-to blocks with "
            "`memory_skill_set`; compose playbooks from skills via "
            "`memory_playbook_set` + `tool_recipe.skills`. Log chats with "
            "`memory_session_*`."
        ),
    )
    register_tools(mcp)
    if settings.mcp_tool_output_normalize_enabled:
        mcp.add_middleware(ToolOutputNormalizeMiddleware())
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
    skills = OrgSkillStore(services.tenant_db)
    strategic = OrgStrategicStore(services.tenant_db)
    agent_state = AgentStateStore(working.client)
    audit = services.audit

    graph: GraphStore | PostgresGraphStore | None = None
    graph_candidate = GraphStore(
        settings.neo4j_url, settings.neo4j_user, settings.neo4j_password
    )
    try:
        await graph_candidate.connect()
        graph = graph_candidate
    except Exception as exc:
        log.warning("graph_store_connect_failed", error=str(exc))
        if settings.postgres_graph_fallback:
            pg_graph = PostgresGraphStore(services.tenant_db)
            try:
                await pg_graph.connect()
                graph = pg_graph
                services.graph = pg_graph
            except Exception as pg_exc:
                log.warning("postgres_graph_connect_failed", error=str(pg_exc))

    if graph is not None:
        services.graph = graph

    facade = MemoryFacade(
        services=services,
        resolver=resolver,
        working=working,
        agent_state=agent_state,
        procedural=procedural,
        skills=skills,
        strategic=strategic,
        graph=graph,
    )

    state = ServerState(
        settings=settings,
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
    - ``POST /llm/prepare`` -- bearer-scoped pre-LLM pipeline (REST mirror of ``context_prepare``).
    - ``POST /gateway/v1/chat/completions`` -- OpenAI-compatible memory-companion proxy
                                              (prepare -> upstream -> capture reply).
    - ``GET  /gateway/v1/models`` -- minimal model catalog for gateway clients.
    - ``POST /compress`` -- bearer-scoped message compression (CCR).
    - ``GET  /compress/retrieve`` -- fetch CCR original by ref.
    - ``POST /tools/normalize`` -- bearer-scoped tool output strip/clean/compress (REST mirror of ``context_normalize``).
    - ``POST /tokens/mint`` -- mint a bearer token (invite code or admin secret).
    - ``POST /tokens/mint/{invite}/{agent}`` -- mint via invite (path params).
    - ``POST /tokens/invites`` -- create invite codes (admin secret).
    - ``GET  /`` -- landing page, service banner JSON, or invite redemption via query params.
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
        return _serve_static("favicon.ico")

    async def apple_touch_icon_route(_: Request) -> Response:
        return _serve_static("apple-touch-icon.png")

    async def static_asset_route(request: Request) -> Response:
        return _serve_static(request.path_params["asset_path"])

    async def metrics_route(_: Request) -> Response:
        with suppress(RuntimeError):
            from teamshared.observability.queues import refresh_queue_metrics
            from teamshared.server.state import get_state

            await refresh_queue_metrics(get_state().working)
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

    async def shared_file_view_route(request: Request) -> Response:
        try:
            from teamshared.server.state import get_state

            return await handle_shared_file_view(request, get_state())
        except RuntimeError:
            return HTMLResponse(
                "<h1>teamshared</h1><p>Server is starting; shared file not ready yet.</p>",
                status_code=503,
            )

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
        if len(turns) > MAX_TURNS_PER_REQUEST:
            return JSONResponse(
                {"error": f"too many turns (max {MAX_TURNS_PER_REQUEST} per request)"},
                status_code=413,
            )
        identity = request.state.agent
        principal = getattr(request.state, "principal", None)
        org_id = principal.org_id if principal else settings.default_org_id
        from teamshared.server.state import get_state

        state = get_state()
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
            v1_per_minute=settings.rate_limit_v1_per_minute,
            admin_export_per_hour=settings.rate_limit_admin_export_per_hour,
            admin_purge_per_hour=settings.rate_limit_admin_purge_per_hour,
        ),
    )
    idempotency_guard = RedisIdempotencyGuard(
        settings.redis_url,
        enabled=settings.rate_limit_enabled,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await rate_limiter.connect()
        app.state.rate_limiter = rate_limiter
        if api_app is not None:
            api_app.state.rate_limiter = rate_limiter
            await idempotency_guard.connect(client=rate_limiter.share_client())
            api_app.state.idempotency_guard = idempotency_guard
        state = await _init_state(settings, services, resolver)
        stop_poll = asyncio.Event()

        async def _queue_metrics_poll() -> None:
            from teamshared.observability.queues import refresh_queue_metrics

            interval = max(5, settings.observability_poll_seconds)
            while not stop_poll.is_set():
                try:
                    await refresh_queue_metrics(state.working)
                except Exception as exc:
                    log.warning("observability_poll_failed", error=str(exc))
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_poll.wait(), timeout=interval)

        poll_task = asyncio.create_task(_queue_metrics_poll())
        log.info("teamshared_server_started", host=settings.host, port=settings.port)
        async with mcp_app.lifespan(app):
            try:
                yield
            finally:
                stop_poll.set()
                poll_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poll_task
                log.info("teamshared_server_stopping")
                await _teardown_state(state)
                await rate_limiter.close()
                app.state.rate_limiter = None
                if api_app is not None:
                    api_app.state.rate_limiter = None
                    await idempotency_guard.close()
                    api_app.state.idempotency_guard = None

    middleware = [
        Middleware(McpSlashMiddleware),
        Middleware(
            BearerAuthMiddleware,
            resolver=resolver,
            auth_disabled=settings.auth_disabled,
        ),
        Middleware(
            ConsoleCsrfCookieMiddleware,
            session_secret=settings.session_secret,
            auth_disabled=settings.auth_disabled,
            session_ttl=settings.console_session_ttl,
        ),
        Middleware(HttpRateLimitMiddleware),
    ]

    app = Starlette(
        routes=[
            Route("/", root_route, methods=["GET"]),
            Route("/favicon.ico", favicon_route, methods=["GET"]),
            Route("/apple-touch-icon.png", apple_touch_icon_route, methods=["GET"]),
            Route("/apple-touch-icon-precomposed.png", apple_touch_icon_route, methods=["GET"]),
            Route("/assets/{asset_path:path}", static_asset_route, methods=["GET"]),
            Route("/health", health_route, methods=["GET"]),
            Route("/metrics", metrics_route, methods=["GET"]),
            Route("/memory", memory_dashboard_route, methods=["GET"]),
            Route("/s/{share_token}", shared_file_view_route, methods=["GET"]),
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
            Route("/compress", handle_compress, methods=["POST"]),
            Route("/compress/retrieve", handle_compress_retrieve, methods=["GET"]),
            Route("/llm/prepare", handle_llm_prepare, methods=["POST"]),
            Route(
                "/gateway/v1/chat/completions",
                handle_gateway_chat_completions,
                methods=["POST"],
            ),
            Route("/gateway/v1/models", handle_gateway_models, methods=["GET"]),
            Route("/tools/normalize", handle_tool_normalize, methods=["POST"]),
            *register_console_routes(settings, services),
            *([Mount("/v1", app=api_app)] if api_app is not None else []),
            Mount("/mcp", app=mcp_app),
        ],
        middleware=middleware,
        lifespan=lifespan,
    )
    instrument_asgi(app)
    return app
