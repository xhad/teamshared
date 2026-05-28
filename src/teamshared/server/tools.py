"""MCP tool definitions.

Each ``@mcp.tool`` function below corresponds to one entry in the public
"MCP tools exposed" surface from the plan. Tools are intentionally small and
side-effect-only at the edges; all real work happens in ``teamshared.memory``.

Agent identity is resolved from the per-request bearer token (see
``teamshared.auth``). If the caller doesn't pass ``agent`` explicitly, we fall back
to the authenticated identity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from teamshared.auth import current_agent, require_current_agent
from teamshared.logging import get_logger
from teamshared.memory.types import MemoryKind, MemoryScope, TimeRange
from teamshared.server.health import check_components
from teamshared.server.state import get_state

log = get_logger(__name__)


def _resolve_agent(explicit: str | None) -> str:
    """Resolve the agent identity for *write* paths.

    Writes need a stable author for attribution, so we fall back to the
    bearer-token identity (or ``"anonymous"`` when auth is disabled). Read
    paths (``memory_recall``, ``memory_episodes_list``) deliberately do not
    use this helper — they default to *no* filter so the shared brain is
    actually shared. Pass an explicit ``agent=`` argument on those tools
    only when you want to narrow results to a single agent's writes.
    """
    if explicit:
        return explicit
    ident = current_agent()
    if ident is None:
        return "anonymous"
    return ident.agent


def _caller_agent() -> str | None:
    """Bearer-token identity of the requester, or ``None`` when unbound.

    Used by read paths that need the caller (e.g. surfacing the caller's own
    working-memory turns in recall) without imposing a filter on durable
    pillars.
    """
    ident = current_agent()
    return ident.agent if ident else None


async def _require_session_owner(session_id: str, caller: str) -> None:
    """Ensure the bearer token owns the working-memory session."""
    state = get_state()
    meta = await state.working.get_metadata(session_id)
    owner = meta.get("agent")
    if owner != caller:
        raise PermissionError(f"session {session_id} belongs to {owner!r}, not {caller!r}")


def register_tools(mcp: Any) -> None:
    """Attach every memory tool to ``mcp``.

    Kept as a function (rather than top-level decorators) so tests can spin up
    a fresh FastMCP instance per case.
    """

    @mcp.tool()
    async def health() -> dict[str, Any]:
        """Liveness + dependency probe.

        Returns ``{"status": "ok", "components": {...}}``. Always cheap; safe
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
    ) -> dict[str, Any]:
        """Write a memory.

        ``fact`` and ``preference`` -> semantic pillar (Mem0 may extract multiple).
        ``event`` -> episodic pillar.
        ``note`` -> semantic with kind=note.
        ``procedure`` -> rejected; use ``memory_procedure_set`` for procedures.
        """
        if kind == "procedure":
            raise ValueError("Use memory_procedure_set for procedures, not memory_remember.")

        state = get_state()
        agent_id = _resolve_agent(agent)
        pillar = "episodic" if kind == "event" else "semantic"
        stored = await state.semantic_episodic.add(
            content,
            agent=agent_id,
            pillar=pillar,
            kind=kind,
            subject=subject,
            tags=tags,
        )
        return {
            "agent": agent_id,
            "pillar": pillar,
            "stored": stored,
            "count": len(stored),
        }

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
                    "every agent's durable memories are visible. Working "
                    "memory is always scoped to the caller regardless."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Hybrid recall across all four memory pillars.

        By default this is **unscoped** on durable pillars (semantic,
        episodic, procedural): callers see every agent's writes. Pass
        ``agent="cursor"`` to narrow to one agent's history. Working memory
        is always caller-scoped because it's per-session conversation state,
        not durable knowledge.

        Records include enough metadata (pillar, agent, created_at, tags)
        for the calling agent to decide what to cite.
        """
        state = get_state()
        scopes = scope or ["semantic", "episodic", "procedural", "working"]
        result = await state.recall.search(
            query,
            agent=agent,
            caller=_caller_agent(),
            scopes=scopes,
            k=k,
            time_range=time_range,
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
    ) -> dict[str, str]:
        """Open a working-memory session and return a ``session_id``."""
        state = get_state()
        agent_id = _resolve_agent(agent)
        session_id = await state.working.open_session(agent_id, topic=topic, ttl=ttl)
        return {"session_id": session_id, "agent": agent_id}

    @mcp.tool()
    async def memory_session_append(
        session_id: Annotated[str, Field(description="Session id from memory_session_open")],
        role: Annotated[str, Field(description="user | assistant | tool | system")],
        content: Annotated[str, Field(description="Turn content")],
    ) -> dict[str, int]:
        """Append a turn to a working-memory session."""
        state = get_state()
        caller = _resolve_agent(None)
        await _require_session_owner(session_id, caller)
        count = await state.working.append_turn(session_id, role, content)
        return {"turn_count": count}

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
        background worker to summarize into durable memories.
        """
        state = get_state()
        caller = _resolve_agent(None)
        await _require_session_owner(session_id, caller)
        return await state.working.close_session(session_id, distill=distill)

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
                    "Default (None) returns every agent's timeline."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Browse the episodic timeline.

        Default behavior is the shared brain: episodes from every agent are
        returned. Pass ``agent="cursor"`` to narrow.
        """
        state = get_state()
        records = await state.semantic_episodic.list_episodes(
            agent=agent,
            topic=topic,
            since=since,
            until=until,
            limit=limit,
        )
        return {
            "count": len(records),
            "episodes": [r.model_dump(mode="json") for r in records],
        }

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
        proc = await state.procedural.get_procedure(name, version=version)
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
        """Insert a new version of a procedure. Each call creates a new version."""
        state = get_state()
        agent_id = _resolve_agent(agent)
        proc = await state.procedural.set_procedure(
            name,
            steps_md,
            agent=agent_id,
            description=description,
            tool_recipe=tool_recipe,
            tags=tags,
        )
        return _serialize_procedure(proc)

    @mcp.tool()
    async def memory_procedures_list(
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List all procedures (latest version of each)."""
        state = get_state()
        rows = await state.procedural.list_procedures(tag=tag, limit=limit)
        return {
            "count": len(rows),
            "procedures": [_serialize_procedure(r) for r in rows],
        }

    @mcp.tool()
    async def memory_graph_relate(
        subject: Annotated[str, Field(description="Source entity")],
        predicate: Annotated[str, Field(description="Relationship label, e.g. 'works_on'")],
        object: Annotated[str, Field(description="Target entity")],
        weight: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Record an explicit relationship in the optional graph store.

        No-op (with a warning) when Neo4j isn't enabled. Use this when you
        learn a structured fact like "alice -> works_on -> teamshared" that vector
        recall would obscure.
        """
        state = get_state()
        if state.graph is None:
            return {"ok": False, "reason": "graph_disabled"}
        agent_id = _resolve_agent(agent)
        await state.graph.add_relation(
            subject, predicate, object, agent=agent_id, weight=weight
        )
        return {"ok": True, "subject": subject, "predicate": predicate, "object": object}

    @mcp.tool()
    async def memory_graph_related(
        name: Annotated[str, Field(description="Entity to expand neighbors of")],
        depth: Annotated[int, Field(ge=1, le=4)] = 2,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> dict[str, Any]:
        """Return entities related to ``name`` via the graph store, up to ``depth`` hops."""
        state = get_state()
        if state.graph is None:
            return {"records": [], "reason": "graph_disabled"}
        records = await state.graph.related(name, depth=depth, limit=limit)
        return {
            "count": len(records),
            "records": [r.model_dump(mode="json") for r in records],
        }

    @mcp.tool()
    async def memory_forget(
        memory_id: Annotated[str, Field(description="Mem0 memory id from a previous recall")],
        reason: Annotated[str, Field(description="Audit reason; required")],
    ) -> dict[str, Any]:
        """Soft-delete a semantic/episodic memory by id.

        Procedural deletes are not supported via this tool; use a direct DB
        operation if you really need to remove a procedure version.
        """
        state = get_state()
        agent_id = _resolve_agent(None)
        log.info("memory_forget", memory_id=memory_id, reason=reason, agent=agent_id)
        ok = await state.semantic_episodic.delete(memory_id)
        await state.audit.record(
            agent=agent_id,
            action="forget",
            target_id=memory_id,
            payload={"reason": reason, "deleted": ok},
        )
        return {"memory_id": memory_id, "deleted": ok}

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
        """Fetch JSON state scoped to the caller's bearer token and ``repo``.

        Returns ``{"repo", "key", "value"}`` where ``value`` is ``null`` when
        unset. Used by clients (e.g. continual-learning) for incremental
        bookkeeping that should not live in git.
        """
        ident = require_current_agent()
        state = get_state()
        value = await state.agent_state.get(ident.state_id, repo, key)
        return {"repo": repo, "key": key, "value": value}

    @mcp.tool()
    async def memory_state_set(
        repo: Annotated[str, Field(description="Workspace slug")],
        key: Annotated[str, Field(description="Opaque state key")],
        value: Annotated[dict[str, Any], Field(description="JSON object to store")],
    ) -> dict[str, Any]:
        """Persist JSON state scoped to the caller's bearer token and ``repo``."""
        ident = require_current_agent()
        state = get_state()
        await state.agent_state.set(ident.state_id, repo, key, value)
        return {"repo": repo, "key": key, "stored": True}


def _serialize_procedure(proc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: v for k, v in proc.items()}
    if "id" in out:
        out["id"] = str(out["id"])
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out
