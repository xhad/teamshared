"""MCP tool definitions.

Each ``@mcp.tool`` function below is a thin shell over
:class:`teamshared.memory.facade.MemoryFacade`: it resolves the current
org-scoped :class:`Principal` and forwards typed arguments. All real work
(permissions, RLS, ingestion, retrieval, ranking) lives in the facade and the
:class:`ProductionServices` it wraps (G2: the tool surface is bound to the same
org-scoped stack as the ``/v1`` REST API).

Identity comes from the per-request bearer token (see ``teamshared.auth``),
which the ``BearerAuthMiddleware`` resolves into a Principal via the
:class:`PrincipalResolver`. Callers may still pass ``agent=`` on write paths to
override attribution; read paths default to the shared brain (no agent filter).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from teamshared.auth import current_agent, current_principal, require_current_agent
from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.memory.types import MemoryKind, MemoryScope, TimeRange
from teamshared.server.health import check_components
from teamshared.server.state import get_state

log = get_logger(__name__)


async def _principal() -> Principal:
    """Resolve the org-scoped Principal for this request.

    The HTTP bearer middleware binds it; for transports without that middleware
    (e.g. stdio in local dev) we fall back to the default-org anonymous agent.
    """
    principal = current_principal()
    if principal is not None:
        return principal
    return await get_state().facade.resolver.anonymous()


def _caller_agent() -> str | None:
    """Bearer-token agent string of the requester (drives working-memory lookup)."""
    ident = current_agent()
    if ident is not None:
        return ident.agent
    principal = current_principal()
    return principal.display if principal else None


def register_tools(mcp: Any) -> None:
    """Attach every memory tool to ``mcp``.

    Kept as a function (rather than top-level decorators) so tests can spin up
    a fresh FastMCP instance per case.
    """

    @mcp.tool()
    async def health() -> dict[str, Any]:
        """Liveness + dependency probe.

        Returns ``{"status", "version", "components": {server, redis, postgres,
        semantic, distiller, graph, ollama}}``. ``semantic`` is the pgvector +
        embedder store (post-Mem0). Optional deps report ``"disabled"`` when off
        and do not degrade overall status. Always cheap; safe
        to poll on a 10s interval. Used by Docker healthcheck and the
        ``/health`` HTTP route.
        """
        state = get_state()
        return await check_components(state)

    @mcp.tool()
    async def memory_remember(
        content: Annotated[str, Field(description="Free-form text to remember")],
        kind: Annotated[
            MemoryKind,
            Field(description="What kind of memory: fact, preference, event, note, procedure"),
        ] = "note",
        subject: Annotated[
            str | None,
            Field(description="Optional subject/entity this memory is about"),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(description="Optional free-form tags"),
        ] = None,
        agent: Annotated[
            str | None,
            Field(description="Override agent identity (defaults to bearer-token identity)"),
        ] = None,
        repo: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace slug of the repo this memory belongs to (e.g. the "
                    "slug used for memory_state). For code/repo-specific work, pass "
                    "your current workspace slug so the memory is scoped to this "
                    "repo (stored as a 'repo:<slug>' tag) and ranks higher when "
                    "recalled from the same repo. Omit for cross-cutting memories."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Write a durable memory into the caller's org.

        ``fact`` / ``preference`` / ``note`` -> semantic pillar. ``event`` ->
        episodic. ``procedure`` -> rejected; use ``memory_procedure_set``.
        Routed through the guarded ingestion pipeline (dedup, PII, injection
        screening, approval routing) under RLS. When ``repo`` is given the
        memory is tagged ``repo:<slug>`` so it can be scoped to that workspace.
        """
        if kind == "procedure":
            raise ValueError("Use memory_procedure_set for procedures, not memory_remember.")
        state = get_state()
        principal = await _principal()
        return await state.facade.remember(
            principal, content=content, kind=kind, subject=subject, tags=tags,
            agent_override=agent, repo=repo,
        )

    @mcp.tool()
    async def memory_recall(
        query: Annotated[str, Field(description="Natural-language query")],
        scope: Annotated[
            list[MemoryScope] | None,
            Field(description="Which pillars to search; default: all"),
        ] = None,
        k: Annotated[int, Field(ge=1, le=50, description="Max records to return")] = 8,
        time_range: Annotated[
            TimeRange | None,
            Field(description="Optional time bounds for episodic/working hits"),
        ] = None,
        agent: Annotated[
            str | None,
            Field(
                description=(
                    "Optional filter — restrict semantic/episodic results to "
                    "this agent's writes. Default (None) is the shared brain: "
                    "every agent's durable memories in the org are visible. "
                    "Working memory is always scoped to the caller regardless."
                ),
            ),
        ] = None,
        repo: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace slug of your current repo. When set, durable "
                    "memories tagged for this repo are boosted (ranked higher); "
                    "nothing is hidden \u2014 cross-repo and un-scoped memories "
                    "still appear. Pass your workspace slug when recalling for "
                    "code/repo-specific work."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Hybrid recall across the four memory pillars, within the caller's org.

        Default behaviour is the shared brain on durable pillars (semantic,
        episodic, procedural): callers see every agent's writes in their org.
        Pass ``agent="cursor"`` to narrow to one agent's history. Pass ``repo``
        to softly boost memories scoped to your current workspace. Working
        memory is always caller-scoped.
        """
        state = get_state()
        principal = await _principal()
        scopes = scope or ["semantic", "episodic", "procedural", "working"]
        result = await state.facade.recall(
            principal,
            query=query,
            scopes=scopes,
            k=k,
            time_range=time_range,
            agent_filter=agent,
            caller_agent=_caller_agent(),
            repo=repo,
        )
        return result.model_dump(mode="json")

    @mcp.tool()
    async def memory_session_open(
        topic: Annotated[
            str | None,
            Field(description="What this session is about (free text)"),
        ] = None,
        ttl: Annotated[
            int | None,
            Field(description="Session TTL in seconds (default from server config)"),
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
        repo: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace slug of the repo this session is about. Memories "
                    "distilled from the session inherit a 'repo:<slug>' tag so "
                    "they stay scoped to this workspace."
                ),
            ),
        ] = None,
    ) -> dict[str, str]:
        """Open a working-memory session and return a ``session_id``."""
        state = get_state()
        principal = await _principal()
        return await state.facade.session_open(
            principal, topic=topic, ttl=ttl, agent_override=agent, repo=repo
        )

    @mcp.tool()
    async def memory_session_append(
        session_id: Annotated[str, Field(description="Session id from memory_session_open")],
        role: Annotated[str, Field(description="user | assistant | tool | system")],
        content: Annotated[str, Field(description="Turn content")],
    ) -> dict[str, int]:
        """Append a turn to a working-memory session."""
        state = get_state()
        principal = await _principal()
        return await state.facade.session_append(
            principal, session_id=session_id, role=role, content=content
        )

    @mcp.tool()
    async def memory_session_close(
        session_id: Annotated[str, Field(description="Session id to close")],
        distill: Annotated[
            bool,
            Field(description="Enqueue for distillation into semantic/episodic memory"),
        ] = True,
    ) -> dict[str, Any]:
        """Close a working-memory session.

        If ``distill`` is true (default), the transcript is queued for the
        background worker to summarize into durable org-scoped memories.
        """
        state = get_state()
        principal = await _principal()
        return await state.facade.session_close(
            principal, session_id=session_id, distill=distill
        )

    @mcp.tool()
    async def memory_episodes_list(
        topic: Annotated[str | None, Field(description="Substring match on topic")] = None,
        since: Annotated[datetime | None, Field(description="Lower bound on created_at")] = None,
        until: Annotated[datetime | None, Field(description="Upper bound on created_at")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
        agent: Annotated[
            str | None,
            Field(
                description=(
                    "Optional filter — restrict to one agent's episodes. "
                    "Default (None) returns every agent's timeline in the org."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Browse the episodic timeline (shared within the org by default)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.episodes_list(
            principal, topic=topic, since=since, until=until, limit=limit, agent_filter=agent
        )

    @mcp.tool()
    async def memory_procedure_get(
        name: Annotated[str, Field(description="Procedure name")],
        version: Annotated[
            int | None,
            Field(description="Specific version (default: latest)"),
        ] = None,
    ) -> dict[str, Any] | None:
        """Fetch a stored procedure by name (and optionally version)."""
        state = get_state()
        principal = await _principal()
        proc = await state.facade.procedure_get(principal, name=name, version=version)
        if proc is None:
            return None
        return _serialize_procedure(proc)

    @mcp.tool()
    async def memory_procedure_set(
        name: Annotated[str, Field(description="Procedure name (stable id)")],
        steps_md: Annotated[str, Field(description="Markdown body the agent will read")],
        description: Annotated[
            str | None, Field(description="One-line summary")
        ] = None,
        tool_recipe: Annotated[
            dict[str, Any] | None,
            Field(description="Optional structured execution recipe (tool calls, params)"),
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Tags for discovery")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Insert a new version of a procedure. Each call creates a new version.

        Routed through the guarded ingestion pipeline (PII redaction, injection
        screening, approval queue). Returns ``status`` (``active``,
        ``pending_approval``, or ``quarantined``); only ``active`` playbooks are
        visible to recall and ``memory_procedure_get``.
        """
        state = get_state()
        principal = await _principal()
        proc = await state.facade.procedure_set(
            principal,
            name=name,
            steps_md=steps_md,
            description=description,
            tool_recipe=tool_recipe,
            tags=tags,
            agent_override=agent,
        )
        return _serialize_procedure(proc)

    @mcp.tool()
    async def memory_procedures_list(
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List all procedures (latest version of each) in the caller's org."""
        state = get_state()
        principal = await _principal()
        result = await state.facade.procedures_list(principal, tag=tag, limit=limit)
        return {
            "count": result["count"],
            "procedures": [_serialize_procedure(r) for r in result["procedures"]],
        }

    @mcp.tool()
    async def memory_graph_relate(
        subject: Annotated[str, Field(description="Source entity")],
        predicate: Annotated[str, Field(description="Relationship label, e.g. 'works_on'")],
        object: Annotated[str, Field(description="Target entity")],
        weight: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Record an explicit relationship in the optional org-scoped graph store.

        No-op (with a reason) when Neo4j isn't enabled. Use this when you learn
        a structured fact like "alice -> works_on -> teamshared" that vector
        recall would obscure.
        """
        state = get_state()
        principal = await _principal()
        return await state.facade.graph_relate(
            principal,
            subject=subject,
            predicate=predicate,
            object_=object,
            weight=weight,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_graph_related(
        name: Annotated[str, Field(description="Entity to expand neighbors of")],
        depth: Annotated[int, Field(ge=1, le=4)] = 2,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> dict[str, Any]:
        """Return entities related to ``name`` via the graph store, up to ``depth`` hops."""
        state = get_state()
        principal = await _principal()
        return await state.facade.graph_related(principal, name=name, depth=depth, limit=limit)

    @mcp.tool()
    async def memory_forget(
        memory_id: Annotated[str, Field(description="memory_items UUID from a previous recall")],
        reason: Annotated[str, Field(description="Audit reason; required")],
    ) -> dict[str, Any]:
        """Soft-delete a semantic/episodic memory by id (requires memory:delete).

        ``memory_id`` is the ``memory_items`` UUID returned by ``memory_recall``
        (post-G2 it is no longer a Mem0 id). Procedural deletes are not
        supported via this tool.
        """
        state = get_state()
        principal = await _principal()
        return await state.facade.forget(principal, memory_id=memory_id, reason=reason)

    @mcp.tool()
    async def memory_state_get(
        repo: Annotated[
            str,
            Field(
                description=(
                    "Workspace slug (absolute path with leading / removed and / replaced by -)"
                )
            ),
        ],
        key: Annotated[
            str,
            Field(description="Opaque state key, e.g. continual-learning/index"),
        ],
    ) -> dict[str, Any]:
        """Fetch JSON state scoped to the caller's org, bearer token, and ``repo``."""
        ident = require_current_agent()
        state = get_state()
        principal = await _principal()
        return await state.facade.state_get(
            principal, state_id=ident.state_id, repo=repo, key=key
        )

    @mcp.tool()
    async def memory_state_set(
        repo: Annotated[str, Field(description="Workspace slug")],
        key: Annotated[str, Field(description="Opaque state key")],
        value: Annotated[dict[str, Any], Field(description="JSON object to store")],
    ) -> dict[str, Any]:
        """Persist JSON state scoped to the caller's org, bearer token, and ``repo``."""
        ident = require_current_agent()
        state = get_state()
        principal = await _principal()
        return await state.facade.state_set(
            principal, state_id=ident.state_id, repo=repo, key=key, value=value
        )


def _serialize_procedure(proc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(proc)
    if "id" in out:
        out["id"] = str(out["id"])
    if "org_id" in out and out["org_id"] is not None:
        out["org_id"] = str(out["org_id"])
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out
