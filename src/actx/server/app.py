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
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from actx.auth import BearerAuthMiddleware, TokenStore
from actx.config import Settings, get_settings
from actx.logging import configure_logging, get_logger
from actx.memory.graph import GraphStore
from actx.memory.procedural import ProceduralStore
from actx.memory.recall import Recall
from actx.memory.semantic import SemanticEpisodicStore
from actx.memory.working import WorkingMemory
from actx.server.state import ServerState, clear_state, set_state
from actx.server.tools import register_tools
from actx.telemetry import instrument_asgi, setup_tracing

log = get_logger(__name__)


def build_mcp(settings: Settings | None = None) -> FastMCP:
    """Build a FastMCP instance with all actx tools registered."""
    settings = settings or get_settings()
    mcp: FastMCP = FastMCP(
        name="actx-memory",
        instructions=(
            "Multi-pillar agent memory. Use `memory_recall` early in a task to "
            "pull relevant facts, episodes, and procedures. Use `memory_remember` "
            "to persist durable facts and `memory_session_*` for working memory."
        ),
    )
    register_tools(mcp)
    return mcp


async def _init_state(settings: Settings) -> ServerState:
    """Connect every backing store and assemble :class:`ServerState`."""
    tokens = TokenStore(settings.tokens_file)
    working = WorkingMemory(settings.redis_url, default_ttl=settings.session_ttl)
    semantic = SemanticEpisodicStore(settings)
    procedural = ProceduralStore(settings.pg_dsn)

    await working.connect()
    await procedural.connect()
    # Mem0 is heavier; connect after the cheap stores so /health is meaningful
    # even when embeddings are temporarily unreachable.
    try:
        await semantic.connect()
    except Exception as exc:
        log.warning("mem0_connect_failed_will_retry_on_demand", error=str(exc))

    recall = Recall(working=working, semantic_episodic=semantic, procedural=procedural)

    graph: GraphStore | None = None
    if settings.neo4j_enabled:
        graph = GraphStore(settings.neo4j_url, settings.neo4j_user, settings.neo4j_password)
        try:
            await graph.connect()
        except Exception as exc:
            log.warning("graph_store_connect_failed", error=str(exc))
            graph = None

    state = ServerState(
        settings=settings,
        tokens=tokens,
        working=working,
        semantic_episodic=semantic,
        procedural=procedural,
        recall=recall,
        graph=graph,
    )
    set_state(state)
    return state


async def _teardown_state(state: ServerState) -> None:
    await state.working.close()
    await state.semantic_episodic.close()
    await state.procedural.close()
    if state.graph is not None:
        await state.graph.close()
    clear_state()


def build_http_app(settings: Settings | None = None) -> Starlette:
    """Build the public-facing Starlette ASGI app.

    Routes:
    - ``GET  /health``  -- unauthenticated probe.
    - ``GET  /``        -- root sentinel (returns a tiny JSON banner).
    - ``ANY  /mcp/*``   -- FastMCP streamable HTTP, gated by bearer auth.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    setup_tracing()

    mcp = build_mcp(settings)
    mcp_app = mcp.http_app(path="/")

    async def health_route(request: Request) -> JSONResponse:
        try:
            from actx.server.state import get_state

            state = get_state()
            components: dict[str, str] = {}
            try:
                await state.working.client.ping()
                components["redis"] = "ok"
            except Exception as exc:
                components["redis"] = f"error: {exc}"
            try:
                async with state.procedural.pool.connection() as conn, conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    await cur.fetchone()
                components["postgres"] = "ok"
            except Exception as exc:
                components["postgres"] = f"error: {exc}"
            components["mem0"] = (
                "ok" if state.semantic_episodic._memory is not None else "not_ready"
            )
            status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
            return JSONResponse({"status": status, "components": components})
        except RuntimeError:
            return JSONResponse({"status": "starting"}, status_code=503)

    async def root_route(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "service": "actx-memory",
                "mcp": "/mcp",
                "health": "/health",
            }
        )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        state = await _init_state(settings)
        log.info("actx_server_started", host=settings.host, port=settings.port)
        async with mcp_app.lifespan(app):
            try:
                yield
            finally:
                log.info("actx_server_stopping")
                await _teardown_state(state)

    tokens = TokenStore(settings.tokens_file)
    middleware = [
        Middleware(
            BearerAuthMiddleware,
            store=tokens,
            auth_disabled=settings.auth_disabled,
        ),
    ]

    app = Starlette(
        routes=[
            Route("/", root_route, methods=["GET"]),
            Route("/health", health_route, methods=["GET"]),
            Mount("/mcp", app=mcp_app),
        ],
        middleware=middleware,
        lifespan=lifespan,
    )
    instrument_asgi(app)
    return app
