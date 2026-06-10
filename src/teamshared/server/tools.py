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
override attribution (each override is audited as ``memory.agent_override``);
read paths default to the shared brain (no agent filter).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import Field

from teamshared import __version__
from teamshared.auth import current_agent, current_principal, require_current_agent
from teamshared.clients.agent_setup import (
    load_teamshared_memory_rule_mdc,
    teamshared_rule_version,
)
from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.memory.types import MemoryKind, MemoryScope, StrategicStatementKind, TimeRange
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
    async def version(
        installed_rule_version: Annotated[
            str | None,
            Field(
                description=(
                    "The `version` from your installed teamshared rule's "
                    "frontmatter (e.g. the value in ~/.cursor/rules/teamshared.mdc). "
                    "Omit if your rule has no version marker."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Report server + memory-rule version and whether the rule needs updating.

        Returns ``{server_version, rule_version, installed_rule_version,
        rule_path, update_available}``. When ``update_available`` is true (the
        installed rule is missing or behind the canonical one), the response also
        includes ``rule_markdown`` — write it verbatim to your rule file
        (Cursor: ``~/.cursor/rules/teamshared.mdc``) to update the user, then
        tell them the memory rule was updated. See the rule's "Staying current".
        """
        rule_md = load_teamshared_memory_rule_mdc()
        current_rule_version = teamshared_rule_version()
        installed = (installed_rule_version or "").strip() or None
        update_available = installed is None or installed != current_rule_version
        out: dict[str, Any] = {
            "server_version": __version__,
            "rule_version": current_rule_version,
            "installed_rule_version": installed,
            "rule_path": "~/.cursor/rules/teamshared.mdc",
            "update_available": update_available,
        }
        if update_available:
            out["rule_markdown"] = rule_md
        return out

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
        github: Annotated[
            str | None,
            Field(
                description=(
                    "GitHub repository as owner/repo (e.g. xhad/teamshared). "
                    "Stored as a 'github:<owner>/<repo>' tag for cross-machine "
                    "association; use with or instead of workspace repo= when "
                    "the same GitHub repo is checked out at different paths."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Write a durable memory into the caller's org.

        ``fact`` / ``preference`` / ``note`` -> semantic pillar. ``event`` ->
        episodic. ``procedure`` -> rejected; use ``memory_procedure_set``.
        Routed through the guarded ingestion pipeline (dedup, PII, injection
        screening, approval routing) under RLS. When ``repo`` / ``github`` are
        given the memory is tagged ``repo:<slug>`` / ``github:<owner>/<repo>``.
        """
        if kind == "procedure":
            raise ValueError("Use memory_procedure_set for procedures, not memory_remember.")
        state = get_state()
        principal = await _principal()
        return await state.facade.remember(
            principal, content=content, kind=kind, subject=subject, tags=tags,
            agent_override=agent, repo=repo, github=github,
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
        github: Annotated[
            str | None,
            Field(
                description=(
                    "GitHub repository as owner/repo. Boosts memories tagged "
                    "github:<owner>/<repo> (portable across checkout paths)."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Hybrid recall across the five memory pillars, within the caller's org.

        Default behaviour is the shared brain on durable pillars (semantic,
        episodic, procedural, strategic): callers see every agent's writes in
        their org. Pass ``agent="cursor"`` to narrow to one agent's history.
        Pass ``repo`` and/or ``github`` to softly boost workspace- or
        GitHub-scoped memories. Working memory is always caller-scoped.
        """
        state = get_state()
        principal = await _principal()
        scopes = scope or ["semantic", "episodic", "procedural", "strategic", "work", "working"]
        result = await state.facade.recall(
            principal,
            query=query,
            scopes=scopes,
            k=k,
            time_range=time_range,
            agent_filter=agent,
            caller_agent=_caller_agent(),
            repo=repo,
            github=github,
        )
        return result.model_dump(mode="json")

    @mcp.tool()
    async def memory_assemble_context(
        task: Annotated[
            str,
            Field(description="What you are about to do (the task/question driving recall)"),
        ],
        repo: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace slug of your current repo. Boosts repo-scoped "
                    "memories in the pack; pass it for code/repo-specific work."
                ),
            ),
        ] = None,
        github: Annotated[
            str | None,
            Field(description="GitHub repository as owner/repo (boosts github-tagged memories)"),
        ] = None,
        open_files: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Paths of files currently open/relevant; their names seed the "
                    "graph-relationship lookup."
                ),
            ),
        ] = None,
        k_per_pillar: Annotated[
            int, Field(ge=1, le=50, description="Max records to recall per pillar")
        ] = 8,
        token_budget: Annotated[
            int,
            Field(
                ge=100,
                le=32000,
                description="Approx token budget for the rendered pack (default 1500)",
            ),
        ] = 1500,
    ) -> dict[str, Any]:
        """Assemble one token-budgeted, cited context pack for a task.

        Fans recall across the durable pillars (semantic, episodic, procedural,
        strategic, work, working) and the optional graph in parallel through the
        secure retrieval path, then ranks and packs the result into a single
        sectioned markdown bundle. Use this once at the start of a task instead
        of issuing serial ``memory_recall`` / ``memory_procedure_get`` /
        ``memory_graph_related`` calls. Returns ``rendered`` (the pack),
        ``tokens_used``, ``counts_by_pillar``, and the kept ``records``.
        """
        state = get_state()
        principal = await _principal()
        pack = await state.facade.assemble_context(
            principal,
            task=task,
            repo=repo,
            github=github,
            open_files=open_files,
            k_per_pillar=k_per_pillar,
            token_budget=token_budget,
            caller_agent=_caller_agent(),
        )
        return pack.model_dump(mode="json")

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
        github: Annotated[
            str | None,
            Field(
                description=(
                    "GitHub repository as owner/repo. Distilled memories inherit "
                    "a 'github:<owner>/<repo>' tag."
                ),
            ),
        ] = None,
    ) -> dict[str, str]:
        """Open a working-memory session and return a ``session_id``."""
        state = get_state()
        principal = await _principal()
        return await state.facade.session_open(
            principal, topic=topic, ttl=ttl, agent_override=agent, repo=repo,
            github=github,
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
    async def memory_strategic_statement_get(
        kind: Annotated[
            StrategicStatementKind,
            Field(description="vision, mission, or purpose"),
        ],
    ) -> dict[str, Any] | None:
        """Fetch the active org statement for vision, mission, or purpose."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_statement_get(principal, kind=kind)

    @mcp.tool()
    async def memory_strategic_statement_set(
        kind: Annotated[StrategicStatementKind, Field(description="vision, mission, or purpose")],
        content_md: Annotated[str, Field(description="Markdown body")],
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose a new version of vision, mission, or purpose (requires approval)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_statement_set(
            principal, kind=kind, content_md=content_md, agent_override=agent,
        )

    @mcp.tool()
    async def memory_strategic_plan_list(
        active_only: Annotated[bool, Field(description="Only active plans")] = True,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List OKR cycles (strategic plans) for the org."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_plan_list(
            principal, active_only=active_only, limit=limit,
        )

    @mcp.tool()
    async def memory_strategic_plan_get(
        plan_id: Annotated[str, Field(description="Plan UUID")],
        include_tree: Annotated[
            bool, Field(description="Include objectives, key results, initiatives")
        ] = True,
    ) -> dict[str, Any] | None:
        """Fetch one strategic plan, optionally with the full OKR tree."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_plan_get(
            principal, plan_id=plan_id, include_tree=include_tree,
        )

    @mcp.tool()
    async def memory_strategic_plan_set(
        name: Annotated[str, Field(description="Cycle name, e.g. 2026 Q2")],
        period_start: Annotated[date, Field(description="Inclusive start date")],
        period_end: Annotated[date, Field(description="Inclusive end date")],
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose a new OKR cycle (requires approval)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_plan_set(
            principal,
            name=name,
            period_start=period_start,
            period_end=period_end,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_strategic_objective_set(
        plan_id: Annotated[str, Field(description="Parent plan UUID")],
        title: Annotated[str, Field(description="Objective title")],
        description_md: Annotated[str | None, Field(description="Optional description")] = None,
        owner_type: Annotated[str | None, Field(description="user or agent")] = None,
        owner_id: Annotated[str | None, Field(description="Owner UUID")] = None,
        sort_order: Annotated[int, Field(description="Display order")] = 0,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose an objective under a plan (requires approval)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_objective_set(
            principal,
            plan_id=plan_id,
            title=title,
            description_md=description_md,
            owner_type=owner_type,
            owner_id=owner_id,
            sort_order=sort_order,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_strategic_key_result_set(
        objective_id: Annotated[str, Field(description="Parent objective UUID")],
        title: Annotated[str, Field(description="Key result title")],
        description_md: Annotated[str | None, Field(description="Optional description")] = None,
        metric_target: Annotated[float | None, Field(description="Target value")] = None,
        metric_current: Annotated[float | None, Field(description="Current value")] = None,
        metric_unit: Annotated[str | None, Field(description="Unit, e.g. %")] = None,
        track_status: Annotated[
            str, Field(description="on_track, at_risk, off_track, or done")
        ] = "on_track",
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose a key result under an objective (requires approval)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_key_result_set(
            principal,
            objective_id=objective_id,
            title=title,
            description_md=description_md,
            metric_target=metric_target,
            metric_current=metric_current,
            metric_unit=metric_unit,
            track_status=track_status,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_strategic_initiative_set(
        plan_id: Annotated[str, Field(description="Parent plan UUID")],
        title: Annotated[str, Field(description="Initiative title")],
        description_md: Annotated[str | None, Field(description="Optional description")] = None,
        objective_id: Annotated[str | None, Field(description="Aligned objective UUID")] = None,
        key_result_id: Annotated[str | None, Field(description="Aligned key result UUID")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose a strategic initiative (requires approval)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_initiative_set(
            principal,
            plan_id=plan_id,
            title=title,
            description_md=description_md,
            objective_id=objective_id,
            key_result_id=key_result_id,
            agent_override=agent,
        )

    @mcp.tool()
    async def work_list(
        work_status: Annotated[
            str | None,
            Field(description="Filter: backlog, todo, in_progress, blocked, done, cancelled"),
        ] = None,
        assignee: Annotated[
            str | None,
            Field(description="Filter by agent name or user email"),
        ] = None,
        mine: Annotated[
            bool,
            Field(description="Only items assigned to the caller (human or agent)"),
        ] = False,
        initiative_id: Annotated[
            str | None,
            Field(description="Filter to tasks linked to a strategic initiative UUID"),
        ] = None,
        exclude_closed: Annotated[
            bool,
            Field(description="Omit done/cancelled items (default true)"),
        ] = True,
        sort: Annotated[
            str,
            Field(description="Sort key: updated_at, priority, work_status, created_at"),
        ] = "updated_at",
        sort_dir: Annotated[str, Field(description="asc or desc")] = "desc",
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List org work items (shared task queue for humans and agents)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_list(
            principal,
            work_status=work_status,
            assignee=assignee,
            mine=mine,
            initiative_id=initiative_id,
            exclude_closed=exclude_closed,
            sort=sort,
            sort_dir=sort_dir,
            limit=limit,
        )

    @mcp.tool()
    async def work_get(
        work_id: Annotated[str, Field(description="Work item UUID")],
    ) -> dict[str, Any] | None:
        """Fetch one work item by id."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_get(principal, work_id=work_id)

    @mcp.tool()
    async def work_create(
        title: Annotated[str, Field(description="Short task title")],
        description_md: Annotated[str | None, Field(description="Optional markdown body")] = None,
        tags: Annotated[list[str] | None, Field(description="Optional tags")] = None,
        work_status: Annotated[
            str, Field(description="backlog, todo, in_progress, blocked, done, cancelled")
        ] = "todo",
        priority: Annotated[str, Field(description="urgent, high, normal, low")] = "normal",
        assignee_type: Annotated[str | None, Field(description="user or agent")] = None,
        assignee_id: Annotated[str | None, Field(description="Assignee UUID")] = None,
        assignee_agent: Annotated[
            str | None, Field(description="Assign to agent by name (e.g. cursor)")
        ] = None,
        assignee_email: Annotated[
            str | None, Field(description="Assign to org member by email")
        ] = None,
        initiative_id: Annotated[
            str | None, Field(description="Optional strategic initiative UUID")
        ] = None,
        due_at: Annotated[datetime | None, Field(description="Optional due datetime")] = None,
        repo: Annotated[str | None, Field(description="Optional workspace slug tag")] = None,
        github: Annotated[str | None, Field(description="Optional owner/repo tag")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Create a work item. Agent writes require approval; human console writes are immediate."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_create(
            principal,
            title=title,
            description_md=description_md,
            tags=tags,
            work_status=work_status,
            priority=priority,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            assignee_agent=assignee_agent,
            assignee_email=assignee_email,
            initiative_id=initiative_id,
            due_at=due_at,
            repo=repo,
            github=github,
            agent_override=agent,
        )

    @mcp.tool()
    async def work_update(
        work_id: Annotated[str, Field(description="Work item UUID")],
        title: Annotated[str | None, Field(description="New title")] = None,
        description_md: Annotated[str | None, Field(description="New markdown body")] = None,
        tags: Annotated[list[str] | None, Field(description="Replace tags")] = None,
        work_status: Annotated[str | None, Field(description="Workflow status")] = None,
        priority: Annotated[str | None, Field(description="urgent, high, normal, low")] = None,
        blocked_reason: Annotated[str | None, Field(description="Why blocked (when status=blocked)")] = None,
        assignee_type: Annotated[str | None, Field(description="user or agent")] = None,
        assignee_id: Annotated[str | None, Field(description="Assignee UUID")] = None,
        assignee_agent: Annotated[str | None, Field(description="Assign to agent by name")] = None,
        assignee_email: Annotated[str | None, Field(description="Assign to user by email")] = None,
        initiative_id: Annotated[str | None, Field(description="Strategic initiative UUID")] = None,
        due_at: Annotated[datetime | None, Field(description="Due datetime")] = None,
        repo: Annotated[str | None, Field(description="Workspace slug tag")] = None,
        github: Annotated[str | None, Field(description="owner/repo tag")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any] | None:
        """Update a work item (status, assignee, priority, etc.). No re-approval required."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_update(
            principal,
            work_id=work_id,
            title=title,
            description_md=description_md,
            tags=tags,
            work_status=work_status,
            priority=priority,
            blocked_reason=blocked_reason,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            assignee_agent=assignee_agent,
            assignee_email=assignee_email,
            initiative_id=initiative_id,
            due_at=due_at,
            repo=repo,
            github=github,
            agent_override=agent,
        )

    @mcp.tool()
    async def work_close(
        work_id: Annotated[str, Field(description="Work item UUID")],
        work_status: Annotated[
            str, Field(description="done or cancelled")
        ] = "done",
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any] | None:
        """Mark a work item done or cancelled."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_close(
            principal, work_id=work_id, work_status=work_status, agent_override=agent,
        )

    @mcp.tool()
    async def work_comment_add(
        work_id: Annotated[str, Field(description="Work item UUID")],
        body: Annotated[str, Field(description="Comment text (markdown ok)")],
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Add a comment to a work item."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_comment_add(
            principal, work_id=work_id, body=body, agent_override=agent,
        )

    @mcp.tool()
    async def work_comment_list(
        work_id: Annotated[str, Field(description="Work item UUID")],
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List comments on a work item (oldest first)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_comment_list(
            principal, work_id=work_id, limit=limit,
        )

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
