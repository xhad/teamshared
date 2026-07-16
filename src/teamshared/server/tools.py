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
from typing import Annotated, Any, cast
from uuid import UUID

from pydantic import Field

from teamshared import __version__
from teamshared.auth import current_agent, current_principal, require_current_agent
from teamshared.clients.agent_setup import (
    load_teamshared_memory_rule_mdc,
    teamshared_rule_version,
)
from teamshared.compress.ccr_store import org_scope_from_id
from teamshared.compress.context_prepare import run_context_prepare
from teamshared.compress.engine import compress_messages_with_ccr
from teamshared.compress.factory import ccr_store_from_working
from teamshared.compress.tool_output import normalize_tool_output
from teamshared.identity.principal import Principal
from teamshared.logging import get_logger
from teamshared.memory.request_context import RequestContext
from teamshared.memory.types import (
    DEFAULT_RECALL_SCOPES,
    AssigneeType,
    KeyResultTrackStatus,
    MemoryKind,
    MemoryScope,
    ProjectStatusState,
    ProjectView,
    SessionRole,
    StrategicEntityType,
    StrategicStatementKind,
    TimeRange,
    ToolCatalogScope,
    WorkItemType,
    WorkPriority,
    WorkSort,
    WorkSortDir,
    WorkStatus,
)
from teamshared.server.health import check_components
from teamshared.server.state import get_state
from teamshared.server.tool_catalog import list_tools

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


def _integration_ctx(principal: Principal) -> RequestContext:
    """Build a RequestContext for an integration tool call."""
    from teamshared.server.state import get_state as _get_state

    services = _get_state().services
    return RequestContext(
        principal=principal, db=services.tenant_db, authorizer=services.authorizer(),
    )


async def _resolve_integration(state: Any, principal: Principal, kind: str) -> UUID:
    """Find the (first) connected connector of ``kind`` for the caller's org."""
    ctx = _integration_ctx(principal)
    items = await state.services.connectors.list_connectors(ctx)
    matches = [i for i in items if i.get("kind") == kind and i.get("status") == "connected"]
    if not matches:
        raise ValueError(
            f"no connected {kind!r} integration for this org; connect one at /app/connections"
        )
    return UUID(matches[0]["id"])


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
    async def context_compress(
        messages: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "OpenAI-style chat messages to compress before sending to an LLM. "
                    "User messages are preserved; long tool/assistant/system blocks shrink."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Compress a prompt payload before it reaches an LLM.

        Shrinks JSON tool outputs, logs, and long text using SmartCrusher-lite
        sampling. Originals are stored in CCR (Redis) with ``ref=`` markers for
        ``context_retrieve``. Always runs; tune thresholds via ``TEAMSHARED_COMPRESS_*``.
        """
        principal = await _principal()
        state = get_state()
        store = ccr_store_from_working(state.settings, state.working)
        result = await compress_messages_with_ccr(
            state.settings,
            messages,
            org_scope=org_scope_from_id(principal.org_id),
            store=store,
        )
        return {
            "messages": result.messages,
            "compressed": result.compressed,
            "stats": {
                "original_chars": result.stats.original_chars,
                "compressed_chars": result.stats.compressed_chars,
                "chars_saved": result.stats.chars_saved,
                "ratio": result.stats.ratio,
                "messages_touched": result.stats.messages_touched,
                "refs": result.stats.refs,
            },
        }

    @mcp.tool()
    async def context_retrieve(
        ref: Annotated[
            str,
            Field(description="CCR ref from a compressed message (ref=ccr_...)"),
        ],
    ) -> dict[str, Any]:
        """Retrieve the original content for a compressed block via CCR ref."""
        principal = await _principal()
        state = get_state()
        store = ccr_store_from_working(state.settings, state.working)
        content = await store.get(org_scope_from_id(principal.org_id), ref)
        if content is None:
            return {"ref": ref, "found": False, "content": None}
        return {"ref": ref, "found": True, "content": content}

    @mcp.tool()
    async def context_prepare(
        messages: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "OpenAI-style chat messages to run through the pre-LLM pipeline. "
                    "Provide this or `prompt`."
                ),
            ),
        ] = None,
        prompt: Annotated[
            str | None,
            Field(description="Latest user prompt when you do not have full message history."),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(description="Working-memory session to append the user turn to."),
        ] = None,
        repo: Annotated[
            str | None,
            Field(description="Workspace slug for scoped recall enrichment."),
        ] = None,
        github: Annotated[
            str | None,
            Field(description="GitHub `owner/repo` for scoped recall enrichment."),
        ] = None,
        append_session: Annotated[
            bool,
            Field(description="Append the latest user message to the working session."),
        ] = True,
        enrich: Annotated[
            bool,
            Field(description="Assemble org memory and append as `additional_context`."),
        ] = True,
        token_budget: Annotated[
            int | None,
            Field(description="Soft token cap for assembled context."),
        ] = None,
    ) -> dict[str, Any]:
        """Pre-LLM pipeline: session append → compress incoming history → enrich.

        Returns compressed ``messages``, optional ``additional_context`` (org memory),
        ``session_id``, and ``stats``. Use before sending a turn to your LLM when you
        want teamshared to shrink tool bloat and inject recall. Server-side MCP
        middleware already normalizes teamshared tool responses; this covers the
        rest of the prompt.
        """
        principal = await _principal()
        state = get_state()
        try:
            return await run_context_prepare(
                state.settings,
                state.facade,
                principal,
                state.working,
                messages=messages,
                prompt=prompt,
                session_id=session_id,
                repo=repo,
                github=github,
                append_session=append_session,
                enrich=enrich,
                token_budget=token_budget,
            )
        except ValueError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def context_commit(
        summary: Annotated[
            str,
            Field(description="Faithful summary of your reply — appended as the assistant turn."),
        ],
        session_id: Annotated[
            str | None,
            Field(
                description=(
                    "Working-memory session to commit to. Omit to resolve it from the "
                    "conversation/active-session state pointer (requires repo)."
                ),
            ),
        ] = None,
        facts: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "Durable memories to write in the same call: "
                    '[{"content": "...", "kind": "fact|preference|event|note", '
                    '"subject": "...", "tags": [...]}]. Only include things still '
                    "true next week."
                ),
            ),
        ] = None,
        repo: Annotated[
            str | None,
            Field(description="Workspace slug; scopes fact tags and the state pointer."),
        ] = None,
        github: Annotated[
            str | None,
            Field(description="GitHub owner/repo tag for the facts."),
        ] = None,
        close: Annotated[
            bool,
            Field(
                description=(
                    "Close the session (queueing distillation) and clear the state "
                    "pointer. Pass true when the task is done or the user says goodbye."
                ),
            ),
        ] = False,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Turn-end batch: assistant summary + durable writes + optional close.

        One call replaces the end-of-turn memory_session_append +
        memory_remember (+ memory_session_close + memory_state_set) sequence.
        The append self-heals expired sessions; the response's ``session_id``
        is authoritative. Returns ``{session_id, turn_count, reopened,
        memories, closed}``.
        """
        ident = current_agent()
        state = get_state()
        principal = await _principal()
        return await state.facade.session_commit(
            principal,
            state_id=ident.state_id if ident else None,
            session_id=session_id,
            summary=summary,
            facts=facts,
            repo=repo,
            github=github,
            close=close,
            agent_override=agent,
        )

    @mcp.tool()
    async def context_normalize(
        tool_name: Annotated[
            str,
            Field(description="Name of the tool whose output you are trimming."),
        ],
        output: Annotated[
            str,
            Field(description="Raw tool output string (usually JSON)."),
        ],
    ) -> dict[str, Any]:
        """Strip, clean, and compress a non-teamshared tool output for agent context.

        Trims recall-style payloads, shrinks large JSON/logs, and stores originals
        in CCR when compressed. Prefer letting MCP middleware handle teamshared
        tools automatically; call this for Shell, Grep, or other harness tools.
        """
        principal = await _principal()
        state = get_state()
        store = ccr_store_from_working(state.settings, state.working)
        normalized = await normalize_tool_output(
            state.settings,
            tool_name,
            output,
            org_scope=org_scope_from_id(principal.org_id),
            store=store,
        )
        return {
            "output": normalized.body,
            "compressed": normalized.compressed,
            "cleaned": normalized.cleaned,
            "stats": {
                "chars_saved": normalized.chars_saved,
                "ref": normalized.ref,
            },
        }

    @mcp.tool()
    async def memory_tools_catalog(
        scope: Annotated[
            ToolCatalogScope,
            Field(description="memory, work, or all tool groups"),
        ] = "all",
        tier: Annotated[
            str | None,
            Field(description="Optional filter: core, extended, or human"),
        ] = None,
    ) -> dict[str, Any]:
        """Discover teamshared MCP tools by tier and group with copy-paste examples.

        Call once per session when unsure which tool to use. Also returns
        ``tool_recipe_shapes`` documenting playbook ``tool_recipe`` JSON.
        """
        return list_tools(scope=scope, tier=tier)

    @mcp.tool()
    async def memory_remember(
        content: Annotated[str, Field(description="Free-form text to remember")],
        kind: Annotated[
            MemoryKind,
            Field(description="fact, preference, event, or note (not procedure/skill)"),
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
        episodic. ``procedure`` / ``skill`` -> rejected; use ``memory_procedure_set`` /
        ``memory_skill_set``.
        Routed through the guarded ingestion pipeline (dedup, PII, injection
        screening) under RLS. When ``repo`` / ``github`` are
        given the memory is tagged ``repo:<slug>`` / ``github:<owner>/<repo>``.
        """
        if kind == "procedure":
            raise ValueError(
                'Use memory_procedure_set (or memory_playbook_set), not memory_remember. '
                'Example: memory_procedure_set(name="ship-pr", steps_md="# Ship\\n1. ...")'
            )
        if kind == "skill":
            raise ValueError(
                'Use memory_skill_set, not memory_remember. '
                'Example: memory_skill_set(name="ship-pr", body_md="# Ship PR\\n1. ...")'
            )
        state = get_state()
        principal = await _principal()
        return await state.facade.remember(
            principal, content=content, kind=kind, subject=subject, tags=tags,
            agent_override=agent, repo=repo, github=github,
        )

    @mcp.tool()
    async def memory_soul_get() -> dict[str, Any]:
        """Return this person's private soul for the current org.

        The soul is a tiny compressed identity block (who they are, style,
        likes/dislikes, dos/don'ts). Empty when none yet or the API key is not
        linked to a human account (mint keys from the console while signed in).
        Also returned on ``memory_session_ensure`` as ``soul``.
        """
        state = get_state()
        principal = await _principal()
        return await state.facade.soul_get(principal)

    @mcp.tool()
    async def memory_soul_set(
        body_md: Annotated[
            str,
            Field(
                description=(
                    "Compressed soul markdown (identity, role, style, likes, "
                    "dislikes, dos/don'ts, patterns). Keep short; server caps length."
                ),
            ),
        ],
        agent: Annotated[
            str | None,
            Field(description="Override agent attribution label"),
        ] = None,
    ) -> dict[str, Any]:
        """Replace this person's private soul for the current org.

        Prefer compact structured markdown. Preferences written via
        ``memory_remember(kind=preference)`` also absorb into the soul.
        """
        state = get_state()
        principal = await _principal()
        return await state.facade.soul_set(
            principal, body_md=body_md, agent_override=agent,
        )

    @mcp.tool()
    async def memory_recall(
        query: Annotated[str, Field(description="Natural-language query")],
        scope: Annotated[
            list[MemoryScope] | None,
            Field(
                description=(
                    "Pillars to search. Default (null): durable pillars only "
                    "(semantic, episodic, procedural, skill, strategic, work) — "
                    "working is omitted. Add scope=['working'] when you need this "
                    "chat's open session turns."
                ),
            ),
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
        verbose: Annotated[
            bool,
            Field(description="When false, truncate record content and omit metadata"),
        ] = True,
        explain: Annotated[
            bool,
            Field(description="When true, include per-record retrieval attribution in metadata"),
        ] = False,
    ) -> dict[str, Any]:
        """Hybrid recall across memory pillars within the caller's org.

        Default scope searches durable pillars only (semantic, episodic,
        procedural, skill, strategic, work). Pass ``scope=["working"]`` to
        include this chat's open session turns. Shared brain on durable
        pillars: pass ``agent="cursor"`` only to narrow semantic/episodic.
        For entity/competitor questions use a **short keyword anchor** in
        ``query`` (e.g. ``"mex"``) plus ``repo`` / ``github``. Use
        ``explain=true``; prefer hits with ``matched_keyword: true``.
        """
        state = get_state()
        principal = await _principal()
        scopes = scope or list(DEFAULT_RECALL_SCOPES)
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
            verbose=verbose,
            explain=explain,
        )
        return result.model_dump(mode="json")

    @mcp.tool()
    async def memory_think(
        query: Annotated[
            str,
            Field(description="Question to answer from team memory"),
        ],
        k: Annotated[
            int, Field(ge=1, le=50, description="Max source records to retrieve before synthesis")
        ] = 12,
        repo: Annotated[
            str | None,
            Field(description="Workspace slug; boosts repo-scoped memories in retrieval"),
        ] = None,
        github: Annotated[
            str | None,
            Field(description="GitHub owner/repo; boosts github-tagged memories"),
        ] = None,
        token_budget: Annotated[
            int,
            Field(ge=200, le=8000, description="Approx token budget for source packing"),
        ] = 1500,
    ) -> dict[str, Any]:
        """Synthesized answer with citations and gap analysis (GBrain ``think`` parity).

        Runs durable recall (default scope excludes working), then composes a
        cited prose answer plus explicit gaps. For named-entity or competitor
        questions, call ``memory_recall`` with a short keyword anchor first —
        synthesis quality depends on retrieval. Prefer ``memory_think`` when
        you need prose + gaps after recall surfaced hits, or for open strategic
        questions.
        """
        state = get_state()
        principal = await _principal()
        result = await state.facade.think(
            principal,
            query=query,
            k=k,
            repo=repo,
            github=github,
            token_budget=token_budget,
            caller_agent=_caller_agent(),
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

        Fans recall across semantic, episodic, procedural, skill, strategic,
        work, working pillars and the optional graph in parallel through the
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
    async def memory_session_ensure(
        repo: Annotated[
            str,
            Field(
                description=(
                    "Workspace slug (absolute path with leading / removed and / "
                    "replaced by -). Keys the conversation/active-session state pointer."
                ),
            ),
        ],
        topic: Annotated[
            str | None,
            Field(description="What this session is about (used when opening a new one)"),
        ] = None,
        github: Annotated[
            str | None,
            Field(description="GitHub owner/repo; distilled memories inherit the tag"),
        ] = None,
        ttl: Annotated[
            int | None,
            Field(description="Session TTL in seconds (default from server config)"),
        ] = None,
        fresh: Annotated[
            bool,
            Field(
                description=(
                    "Force rotation: close any stored session (queueing distillation) "
                    "and open a new one. Pass true on the first turn of a new chat."
                ),
            ),
        ] = False,
        user: Annotated[
            str | None,
            Field(
                description=(
                    "Substantive user request for this turn. When set, appended as the "
                    "user turn in the same call (replaces a separate memory_session_append)."
                ),
            ),
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """One-call session bootstrap: recover the active session or open one.

        Replaces the memory_state_get → memory_session_close →
        memory_session_open → memory_state_set ritual. Reuses the session in
        the ``conversation/active-session`` state pointer when it is still
        open and owned by the caller; otherwise closes it (distilling) and
        opens a fresh one, updating state. Returns ``{session_id, agent,
        resumed, soul, soul_linked}``. When the bearer is linked to a human
        account, ``soul`` is their private compressed identity block for this
        org (may be empty string if not yet written).
        """
        ident = require_current_agent()
        state = get_state()
        principal = await _principal()
        return await state.facade.session_ensure(
            principal,
            state_id=ident.state_id,
            repo=repo,
            topic=topic,
            github=github,
            ttl=ttl,
            fresh=fresh,
            agent_override=agent,
            user=user,
        )

    @mcp.tool()
    async def memory_session_append(
        session_id: Annotated[str, Field(description="Session id from memory_session_open")],
        role: Annotated[SessionRole, Field(description="user, assistant, tool, or system")],
        content: Annotated[str, Field(description="Turn content")],
        repo: Annotated[
            str | None,
            Field(
                description=(
                    "Workspace slug. When set with an active bearer token, reopen "
                    "self-healing updates the conversation/active-session pointer."
                ),
            ),
        ] = None,
        github: Annotated[
            str | None,
            Field(description="GitHub owner/repo tag used when reopening a session"),
        ] = None,
        topic: Annotated[
            str | None,
            Field(description="Session topic used when reopening after expiry"),
        ] = None,
    ) -> dict[str, Any]:
        """Append a turn to a working-memory session (self-healing).

        When ``session_id`` has expired or was closed, a fresh session is
        opened automatically and the turn lands there; the response then
        carries the replacement ``session_id`` and ``reopened: true``. Pass
        ``repo`` (and optionally ``github`` / ``topic``) so reopen preserves
        workspace scope and updates the state pointer without a manual
        ``memory_state_set``.
        """
        ident = current_agent()
        state = get_state()
        principal = await _principal()
        return await state.facade.session_append(
            principal,
            session_id=session_id,
            role=role,
            content=content,
            state_id=ident.state_id if ident else None,
            repo=repo,
            github=github,
            topic=topic,
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
    async def memory_session_get(
        session_id: Annotated[str, Field(description="Session id from memory_session_open")],
    ) -> dict[str, Any]:
        """Read session metadata and turns (debug, handoff, append failure recovery)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.session_get(principal, session_id=session_id)

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
        name: Annotated[str, Field(description="Playbook (procedure) name")],
        version: Annotated[
            int | None,
            Field(description="Specific version (default: latest active)"),
        ] = None,
        expand_skills: Annotated[
            bool,
            Field(description="Inline composed skill bodies into steps_md"),
        ] = False,
    ) -> dict[str, Any] | None:
        """Fetch a stored playbook by name (and optionally version).

        Set ``expand_skills=true`` to resolve ``tool_recipe.skills`` into the
        returned ``steps_md`` / ``content_md`` (same as the background runner).
        """
        state = get_state()
        principal = await _principal()
        proc = await state.facade.procedure_get(
            principal, name=name, version=version, expand_skills=expand_skills,
        )
        if proc is None:
            return None
        return _serialize_procedure(proc)

    @mcp.tool(name="memory_playbook_get")
    async def memory_playbook_get(
        name: Annotated[str, Field(description="Playbook name")],
        version: Annotated[int | None, Field(description="Specific version")] = None,
        expand_skills: Annotated[bool, Field(description="Inline composed skills")] = False,
    ) -> dict[str, Any] | None:
        """Alias for ``memory_procedure_get``."""
        return cast(dict[str, Any] | None, await memory_procedure_get(name=name, version=version, expand_skills=expand_skills))

    @mcp.tool()
    async def memory_procedure_set(
        name: Annotated[str, Field(description="Procedure name (stable id)")],
        steps_md: Annotated[
            str,
            Field(
                description=(
                    "Optional intro markdown before composed skills; "
                    "use tool_recipe.skills for the ordered skill list"
                ),
            ),
        ] = "",
        description: Annotated[
            str | None, Field(description="One-line summary")
        ] = None,
        tool_recipe: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Playbook recipe: "
                    '{"skills": ["lint", "ship-pr"], "loop": {"max_iterations": 3}}. '
                    "See memory_tools_catalog for full shapes."
                ),
            ),
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Tags for discovery")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Insert a new version of a procedure. Each call creates a new version.

        Playbooks are ordered skill collections: set ``tool_recipe.skills`` and
        optional ``steps_md`` intro. Routed through the guarded ingestion pipeline.
        Returns ``status`` (``active`` or ``duplicate``).
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

    @mcp.tool(name="memory_playbook_set")
    async def memory_playbook_set(
        name: Annotated[str, Field(description="Playbook name (stable id)")],
        steps_md: Annotated[
            str, Field(description="Optional intro markdown before composed skills")
        ] = "",
        description: Annotated[str | None, Field(description="One-line summary")] = None,
        tool_recipe: Annotated[
            dict[str, Any] | None,
            Field(description="Ordered skill list: {\"skills\": [\"lint\", \"ship-pr\"]}"),
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Tags for discovery")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Alias for ``memory_procedure_set``."""
        return cast(
            dict[str, Any],
            await memory_procedure_set(
            name=name, steps_md=steps_md, description=description,
            tool_recipe=tool_recipe, tags=tags, agent=agent,
            ),
        )

    @mcp.tool()
    async def memory_procedures_list(
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
        include_body: Annotated[
            bool, Field(description="Include full steps_md and tool_recipe")
        ] = False,
    ) -> dict[str, Any]:
        """List playbooks (latest version of each) in the caller's org."""
        state = get_state()
        principal = await _principal()
        result = await state.facade.procedures_list(
            principal, tag=tag, limit=limit, offset=offset, include_body=include_body,
        )
        return {
            "count": result["count"],
            "procedures": [_serialize_procedure(r) for r in result["procedures"]],
            "next_offset": result.get("next_offset"),
        }

    @mcp.tool(name="memory_playbooks_list")
    async def memory_playbooks_list(
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
        include_body: Annotated[bool, Field(description="Include full steps_md")] = False,
    ) -> dict[str, Any]:
        """Alias for ``memory_procedures_list``."""
        return cast(
            dict[str, Any],
            await memory_procedures_list(
            tag=tag, limit=limit, offset=offset, include_body=include_body,
            ),
        )

    @mcp.tool()
    async def memory_forget_procedure(
        name: Annotated[str, Field(description="Playbook name to soft-delete")],
        reason: Annotated[str, Field(description="Audit reason; required")],
    ) -> dict[str, Any]:
        """Soft-delete all active versions of a playbook by name."""
        state = get_state()
        principal = await _principal()
        return await state.facade.forget_procedure(principal, name=name, reason=reason)

    @mcp.tool()
    async def memory_skill_get(
        name: Annotated[str, Field(description="Skill name")],
        version: Annotated[
            int | None,
            Field(description="Specific version (default: latest active)"),
        ] = None,
    ) -> dict[str, Any] | None:
        """Fetch a stored skill by name (and optionally version)."""
        state = get_state()
        principal = await _principal()
        skill = await state.facade.skill_get(principal, name=name, version=version)
        if skill is None:
            return None
        return _serialize_skill(skill)

    @mcp.tool()
    async def memory_skill_set(
        name: Annotated[str, Field(description="Skill name (stable id)")],
        body_md: Annotated[str, Field(description="Markdown body the agent will read")],
        description: Annotated[
            str | None, Field(description="One-line summary")
        ] = None,
        tool_hints: Annotated[
            dict[str, Any] | None,
            Field(description="Optional structured hints (preferred MCP tools, params)"),
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Tags for discovery")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Insert a new version of a skill. Each call creates a new version.

        Skills are atomic instruction building blocks. Playbooks compose them via
        ``tool_recipe.skills`` on ``memory_procedure_set``. Routed through the
        guarded ingestion pipeline; only ``active`` skills are visible to recall
        and ``memory_skill_get``.
        """
        state = get_state()
        principal = await _principal()
        row = await state.facade.skill_set(
            principal,
            name=name,
            body_md=body_md,
            description=description,
            tool_hints=tool_hints,
            tags=tags,
            agent_override=agent,
        )
        return _serialize_skill(row)

    @mcp.tool()
    async def memory_skills_list(
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
        include_body: Annotated[
            bool, Field(description="Include full body_md and tool_hints")
        ] = False,
    ) -> dict[str, Any]:
        """List all skills (latest version of each) in the caller's org."""
        state = get_state()
        principal = await _principal()
        result = await state.facade.skills_list(
            principal, tag=tag, limit=limit, offset=offset, include_body=include_body,
        )
        return {
            "count": result["count"],
            "skills": [_serialize_skill(r) for r in result["skills"]],
            "next_offset": result.get("next_offset"),
        }

    @mcp.tool()
    async def memory_skill_resolve(
        playbook_name: Annotated[str, Field(description="Playbook whose skills to resolve")],
        playbook_version: Annotated[
            int | None, Field(description="Pin playbook version (default latest)")
        ] = None,
    ) -> dict[str, Any] | None:
        """Resolve a playbook's ``tool_recipe.skills`` refs to full skill records."""
        state = get_state()
        principal = await _principal()
        return await state.facade.skill_resolve(
            principal, playbook_name=playbook_name, playbook_version=playbook_version,
        )

    @mcp.tool()
    async def memory_forget_skill(
        name: Annotated[str, Field(description="Skill name to soft-delete")],
        reason: Annotated[str, Field(description="Audit reason; required")],
    ) -> dict[str, Any]:
        """Soft-delete all active versions of a skill by name."""
        state = get_state()
        principal = await _principal()
        return await state.facade.forget_skill(principal, name=name, reason=reason)

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
        """Propose a new version of vision, mission, or purpose."""
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
        """Propose a new OKR cycle."""
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
        """Propose an objective under a plan."""
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
            KeyResultTrackStatus, Field(description="on_track, at_risk, off_track, or done")
        ] = "on_track",
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose a key result under an objective."""
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
        """Propose a strategic initiative."""
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
    async def memory_strategic_entity_get(
        entity_type: Annotated[
            StrategicEntityType,
            Field(description="objective, key_result, initiative, plan, or statement"),
        ],
        entity_id: Annotated[str, Field(description="Entity UUID")],
    ) -> dict[str, Any] | None:
        """Fetch one strategic entity by type and id."""
        state = get_state()
        principal = await _principal()
        return await state.facade.strategic_entity_get(
            principal, entity_type=entity_type, entity_id=entity_id,
        )

    @mcp.tool()
    async def work_list(
        work_status: Annotated[
            WorkStatus | None,
            Field(description="Filter by workflow status"),
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
        sort: Annotated[WorkSort, Field(description="Sort key")] = "updated_at",
        sort_dir: Annotated[WorkSortDir, Field(description="asc or desc")] = "desc",
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
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
            offset=offset,
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
        description: Annotated[
            str | None, Field(description="Alias for description_md")
        ] = None,
        tags: Annotated[list[str] | None, Field(description="Optional tags")] = None,
        work_status: Annotated[WorkStatus, Field(description="Initial workflow status")] = "todo",
        priority: Annotated[WorkPriority, Field(description="urgent, high, normal, low")] = "normal",
        assignee_type: Annotated[AssigneeType | None, Field(description="Assignee type (user)")] = None,
        assignee_id: Annotated[str | None, Field(description="Assignee UUID")] = None,
        assignee_email: Annotated[
            str | None, Field(description="Assign to org member by email")
        ] = None,
        initiative_id: Annotated[
            str | None, Field(description="Optional strategic initiative UUID")
        ] = None,
        due_at: Annotated[datetime | None, Field(description="Optional due datetime")] = None,
        repo: Annotated[str | None, Field(description="Optional workspace slug tag")] = None,
        github: Annotated[str | None, Field(description="Optional owner/repo tag")] = None,
        project_id: Annotated[
            str | None, Field(description="Add the task to this project UUID")
        ] = None,
        section_id: Annotated[
            str | None, Field(description="Place in this project section UUID")
        ] = None,
        parent_id: Annotated[
            str | None, Field(description="Parent task UUID (makes this a subtask)")
        ] = None,
        start_at: Annotated[datetime | None, Field(description="Optional start datetime")] = None,
        item_type: Annotated[WorkItemType, Field(description="task, milestone, or approval")] = "task",
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Create a work item. Created active immediately for humans and agents (no approval queue)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_create(
            principal,
            title=title,
            description_md=description_md if description_md is not None else description,
            tags=tags,
            work_status=work_status,
            priority=priority,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            assignee_email=assignee_email,
            initiative_id=initiative_id,
            due_at=due_at,
            repo=repo,
            github=github,
            project_id=project_id,
            section_id=section_id,
            parent_id=parent_id,
            start_at=start_at,
            item_type=item_type,
            agent_override=agent,
        )

    @mcp.tool()
    async def work_update(
        work_id: Annotated[str, Field(description="Work item UUID")],
        title: Annotated[str | None, Field(description="New title")] = None,
        description_md: Annotated[str | None, Field(description="New markdown body")] = None,
        tags: Annotated[list[str] | None, Field(description="Replace tags")] = None,
        work_status: Annotated[WorkStatus | None, Field(description="Workflow status")] = None,
        priority: Annotated[WorkPriority | None, Field(description="urgent, high, normal, low")] = None,
        blocked_reason: Annotated[str | None, Field(description="Why blocked (when status=blocked)")] = None,
        assignee_type: Annotated[AssigneeType | None, Field(description="Assignee type (user)")] = None,
        assignee_id: Annotated[str | None, Field(description="Assignee UUID")] = None,
        assignee_email: Annotated[str | None, Field(description="Assign to user by email")] = None,
        initiative_id: Annotated[str | None, Field(description="Strategic initiative UUID")] = None,
        due_at: Annotated[datetime | None, Field(description="Due datetime")] = None,
        repo: Annotated[str | None, Field(description="Workspace slug tag")] = None,
        github: Annotated[str | None, Field(description="owner/repo tag")] = None,
        parent_id: Annotated[
            str | None, Field(description="Parent task UUID (reparent as subtask)")
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any] | None:
        """Update a work item (status, assignee, priority, parent, etc.)."""
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
            assignee_email=assignee_email,
            initiative_id=initiative_id,
            due_at=due_at,
            repo=repo,
            github=github,
            agent_override=agent,
            parent_id=parent_id,
        )

    @mcp.tool()
    async def work_close(
        work_id: Annotated[str, Field(description="Work item UUID")],
        work_status: Annotated[WorkStatus, Field(description="done or cancelled")] = "done",
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
    async def project_create(
        name: Annotated[str, Field(description="Project name")],
        description_md: Annotated[str | None, Field(description="Optional markdown body")] = None,
        team_id: Annotated[str | None, Field(description="Owning team UUID")] = None,
        default_view: Annotated[ProjectView, Field(description="list, board, timeline, or calendar")] = "list",
        color: Annotated[str | None, Field(description="Optional color label")] = None,
        owner_email: Annotated[str | None, Field(description="Owner member email")] = None,
        initiative_id: Annotated[
            str | None, Field(description="Strategic initiative UUID for roll-up")
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Create a project (Asana-style task container)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.project_create(
            principal,
            name=name,
            description_md=description_md,
            team_id=team_id,
            default_view=default_view,
            color=color,
            owner_email=owner_email,
            initiative_id=initiative_id,
            agent_override=agent,
        )

    @mcp.tool()
    async def project_list(
        team_id: Annotated[str | None, Field(description="Filter by team UUID")] = None,
        initiative_id: Annotated[str | None, Field(description="Filter by initiative UUID")] = None,
        include_archived: Annotated[bool, Field(description="Include archived projects")] = False,
        limit: Annotated[int, Field(ge=1, le=200)] = 100,
    ) -> dict[str, Any]:
        """List projects in the org."""
        state = get_state()
        principal = await _principal()
        return await state.facade.project_list(
            principal,
            team_id=team_id,
            initiative_id=initiative_id,
            include_archived=include_archived,
            limit=limit,
        )

    @mcp.tool()
    async def project_get(
        project_id: Annotated[str, Field(description="Project UUID")],
        include_items: Annotated[
            bool, Field(description="Include the project's tasks (board view)")
        ] = True,
    ) -> dict[str, Any] | None:
        """Fetch a project with its sections, latest status, and optionally its tasks."""
        state = get_state()
        principal = await _principal()
        return await state.facade.project_get(
            principal, project_id=project_id, include_items=include_items,
        )

    @mcp.tool()
    async def project_update(
        project_id: Annotated[str, Field(description="Project UUID")],
        name: Annotated[str | None, Field(description="New name")] = None,
        description_md: Annotated[str | None, Field(description="New markdown body")] = None,
        default_view: Annotated[str | None, Field(description="list/board/timeline/calendar")] = None,
        color: Annotated[str | None, Field(description="Color label")] = None,
        initiative_id: Annotated[str | None, Field(description="Strategic initiative UUID")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any] | None:
        """Update project metadata."""
        state = get_state()
        principal = await _principal()
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if description_md is not None:
            fields["description_md"] = description_md
        if default_view is not None:
            fields["default_view"] = default_view
        if color is not None:
            fields["color"] = color
        if initiative_id is not None:
            fields["initiative_id"] = initiative_id
        return await state.facade.project_update(
            principal, project_id=project_id, fields=fields, agent_override=agent,
        )

    @mcp.tool()
    async def project_archive(
        project_id: Annotated[str, Field(description="Project UUID")],
        archived: Annotated[bool, Field(description="True to archive, False to restore")] = True,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any] | None:
        """Archive or restore a project."""
        state = get_state()
        principal = await _principal()
        return await state.facade.project_archive(
            principal, project_id=project_id, archived=archived,
        )

    @mcp.tool()
    async def project_section_add(
        project_id: Annotated[str, Field(description="Project UUID")],
        name: Annotated[str, Field(description="Section name (list group / board column)")],
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Add an ordered section to a project."""
        state = get_state()
        principal = await _principal()
        return await state.facade.project_section_add(
            principal, project_id=project_id, name=name,
        )

    @mcp.tool()
    async def project_section_list(
        project_id: Annotated[str, Field(description="Project UUID")],
    ) -> dict[str, Any]:
        """List a project's sections in order."""
        state = get_state()
        principal = await _principal()
        return await state.facade.project_section_list(principal, project_id=project_id)

    @mcp.tool()
    async def project_status_post(
        project_id: Annotated[str, Field(description="Project UUID")],
        state_label: Annotated[
            ProjectStatusState | None, Field(description="on_track, at_risk, or off_track")
        ] = None,
        status: Annotated[
            ProjectStatusState | None, Field(description="Alias for state_label")
        ] = None,
        body_md: Annotated[str | None, Field(description="Status note (markdown ok)")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Post a project status update (on-track / at-risk / off-track banner)."""
        resolved = state_label if state_label is not None else (status or "on_track")
        state = get_state()
        principal = await _principal()
        return await state.facade.project_status_post(
            principal, project_id=project_id, state=resolved, body_md=body_md,
            agent_override=agent,
        )

    @mcp.tool()
    async def work_add_to_project(
        work_id: Annotated[str, Field(description="Work item UUID")],
        project_id: Annotated[str, Field(description="Project UUID")],
        section_id: Annotated[str | None, Field(description="Optional section UUID")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Add a task to a project (tasks can belong to multiple projects)."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_add_to_project(
            principal, work_id=work_id, project_id=project_id, section_id=section_id,
            agent_override=agent,
        )

    @mcp.tool()
    async def work_remove_from_project(
        work_id: Annotated[str, Field(description="Work item UUID")],
        project_id: Annotated[str, Field(description="Project UUID")],
    ) -> dict[str, Any]:
        """Remove a task from a project."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_remove_from_project(
            principal, work_id=work_id, project_id=project_id,
        )

    @mcp.tool()
    async def work_move(
        work_id: Annotated[str, Field(description="Work item UUID")],
        project_id: Annotated[str, Field(description="Project UUID")],
        section_id: Annotated[str | None, Field(description="Target section UUID")] = None,
        sort_order: Annotated[float, Field(description="Fractional rank within section")] = 0.0,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any] | None:
        """Move a task to a section and/or reorder it within a project."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_move(
            principal, work_id=work_id, project_id=project_id, section_id=section_id,
            sort_order=sort_order, agent_override=agent,
        )

    @mcp.tool()
    async def work_subtasks_list(
        work_id: Annotated[str, Field(description="Parent work item UUID")],
    ) -> dict[str, Any]:
        """List subtasks of a work item. Create subtasks via work_create with parent_id."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_subtasks_list(principal, work_id=work_id)

    @mcp.tool()
    async def work_dependency_add(
        blocker_id: Annotated[
            str | None, Field(description="Task that must finish first")
        ] = None,
        blocked_id: Annotated[
            str | None, Field(description="Task that is blocked")
        ] = None,
        work_id: Annotated[
            str | None, Field(description="Alias for blocked_id (the task that waits)")
        ] = None,
        depends_on_id: Annotated[
            str | None, Field(description="Alias for blocker_id (the task it waits on)")
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Add a dependency: blocker must finish before blocked can proceed.

        Pass ``blocker_id`` + ``blocked_id``, or equivalently
        ``work_id`` (blocked) + ``depends_on_id`` (blocker).
        """
        blocker, blocked = _resolve_dependency_ids(
            blocker_id=blocker_id, blocked_id=blocked_id,
            work_id=work_id, depends_on_id=depends_on_id,
        )
        state = get_state()
        principal = await _principal()
        return await state.facade.work_dependency_add(
            principal, blocker_id=blocker, blocked_id=blocked, agent_override=agent,
        )

    @mcp.tool()
    async def work_dependency_remove(
        blocker_id: Annotated[str | None, Field(description="Blocker task UUID")] = None,
        blocked_id: Annotated[str | None, Field(description="Blocked task UUID")] = None,
        work_id: Annotated[
            str | None, Field(description="Alias for blocked_id (the task that waits)")
        ] = None,
        depends_on_id: Annotated[
            str | None, Field(description="Alias for blocker_id (the task it waits on)")
        ] = None,
    ) -> dict[str, Any]:
        """Remove a task dependency."""
        blocker, blocked = _resolve_dependency_ids(
            blocker_id=blocker_id, blocked_id=blocked_id,
            work_id=work_id, depends_on_id=depends_on_id,
        )
        state = get_state()
        principal = await _principal()
        return await state.facade.work_dependency_remove(
            principal, blocker_id=blocker, blocked_id=blocked,
        )

    @mcp.tool()
    async def work_dependencies_list(
        work_id: Annotated[str, Field(description="Work item UUID")],
    ) -> dict[str, Any]:
        """List what a task is blocked by and what it blocks."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_dependencies_list(principal, work_id=work_id)

    @mcp.tool()
    async def work_follower_add(
        work_id: Annotated[str, Field(description="Work item UUID")],
        follower_email: Annotated[str | None, Field(description="Member email to add")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Add a follower/collaborator to a task by member email."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_follower_add(
            principal, work_id=work_id,
            follower_email=follower_email, agent_override=agent,
        )

    @mcp.tool()
    async def work_follower_remove(
        work_id: Annotated[str, Field(description="Work item UUID")],
        follower_email: Annotated[str | None, Field(description="Member email to remove")] = None,
    ) -> dict[str, Any]:
        """Remove a follower from a task by member email."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_follower_remove(
            principal, work_id=work_id,
            follower_email=follower_email,
        )

    @mcp.tool()
    async def work_followers_list(
        work_id: Annotated[str, Field(description="Work item UUID")],
    ) -> dict[str, Any]:
        """List followers/collaborators on a task."""
        state = get_state()
        principal = await _principal()
        return await state.facade.work_followers_list(principal, work_id=work_id)

    @mcp.tool()
    async def memory_graph_relate(
        subject: Annotated[str, Field(description="Source entity")],
        predicate: Annotated[str, Field(description="Relationship label, e.g. 'works_on'")],
        object_entity: Annotated[
            str | None, Field(description="Target entity")
        ] = None,
        object: Annotated[
            str | None, Field(description="Alias for object_entity")
        ] = None,
        weight: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Record an explicit relationship in the optional org-scoped graph store.

        No-op (with a reason) when the graph isn't enabled. Use this when you
        learn a structured fact like "alice -> works_on -> teamshared" that
        vector recall would obscure. ``predicate`` must be a registered link
        type (see ``memory_ontology_list``).
        """
        target = object_entity if object_entity is not None else object
        if target is None:
            raise ValueError("object_entity (alias: object) is required")
        state = get_state()
        principal = await _principal()
        return await state.facade.graph_relate(
            principal,
            subject=subject,
            predicate=predicate,
            object_=target,
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
    async def memory_entity_view(
        slug: Annotated[str, Field(description="Entity slug (wiki topic slug or ontology entity slug)")],
    ) -> dict[str, Any]:
        """Roll up wiki, memories, graph neighbors, and work for one entity."""
        state = get_state()
        principal = await _principal()
        return await state.facade.entity_view(principal, slug=slug)

    @mcp.tool()
    async def memory_ontology_list() -> dict[str, Any]:
        """List org ontology schema: link types, object kinds, interfaces, action types."""
        state = get_state()
        principal = await _principal()
        return await state.facade.ontology_list(principal)

    @mcp.tool()
    async def memory_ontology_propose_entity(
        name: Annotated[str, Field(description="Display name for the entity")],
        kind_name: Annotated[
            str | None,
            Field(description="Registered object kind, e.g. Person or Project"),
        ] = None,
        kind: Annotated[str | None, Field(description="Alias for kind_name")] = None,
        properties: Annotated[
            dict[str, Any] | None,
            Field(description="Optional JSON properties matching the kind schema"),
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Propose a typed ontology entity (active immediately)."""
        resolved_kind = kind_name if kind_name is not None else kind
        if resolved_kind is None:
            raise ValueError("kind_name (alias: kind) is required")
        state = get_state()
        principal = await _principal()
        return await state.facade.ontology_propose_entity(
            principal,
            kind_name=resolved_kind,
            name=name,
            properties=properties,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_ontology_link_type_set(
        name: Annotated[str, Field(description="Link predicate name, e.g. depends_on")],
        description: Annotated[str | None, Field(description="Human-readable description")] = None,
        from_kinds: Annotated[
            list[str] | None, Field(description="Allowed subject kinds (empty = any)")
        ] = None,
        to_kinds: Annotated[
            list[str] | None, Field(description="Allowed object kinds (empty = any)")
        ] = None,
        cardinality: Annotated[str, Field(description="one_to_many | many_to_many")] = "many_to_many",
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Register or update a custom org link type."""
        state = get_state()
        principal = await _principal()
        return await state.facade.ontology_link_type_set(
            principal,
            name=name,
            description=description,
            from_kinds=from_kinds,
            to_kinds=to_kinds,
            cardinality=cardinality,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_ontology_object_kind_set(
        name: Annotated[str, Field(description="Object kind name, e.g. Vendor")],
        description: Annotated[str | None, Field(description="Human-readable description")] = None,
        properties_schema: Annotated[
            dict[str, Any] | None, Field(description="JSON schema for entity properties")
        ] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Register or update a custom org object kind."""
        state = get_state()
        principal = await _principal()
        return await state.facade.ontology_object_kind_set(
            principal,
            name=name,
            description=description,
            properties_schema=properties_schema,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_action_apply(
        parameters: Annotated[
            dict[str, Any], Field(description="Parameters matching the action schema")
        ],
        action_name: Annotated[
            str | None, Field(description="Registered action type name, e.g. link_entities")
        ] = None,
        action: Annotated[str | None, Field(description="Alias for action_name")] = None,
        agent: Annotated[str | None, Field(description="Override agent identity")] = None,
    ) -> dict[str, Any]:
        """Execute a governed ontology action and write an audit log entry."""
        resolved_action = action_name if action_name is not None else action
        if resolved_action is None:
            raise ValueError("action_name (alias: action) is required")
        state = get_state()
        principal = await _principal()
        return await state.facade.action_apply(
            principal,
            action_name=resolved_action,
            parameters=parameters,
            agent_override=agent,
        )

    @mcp.tool()
    async def memory_action_log_list(
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> dict[str, Any]:
        """List recent governed action executions for the org."""
        state = get_state()
        principal = await _principal()
        return await state.facade.action_log_list(principal, limit=limit)

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

    # --- Gmail + Slack + Discord integrations -----------------------------

    @mcp.tool()
    async def integration_list() -> dict[str, Any]:
        """List the caller's org's connected Gmail/Slack/Discord integrations.

        Returns each connection's id, kind, name, status, and owning account.
        Use this to discover which integration a ``integration_search`` /
        ``integration_send`` call should target.
        """
        state = get_state()
        principal = await _principal()
        ctx = _integration_ctx(principal)
        items = await state.services.connectors.list_connectors(ctx)
        return {"integrations": items}

    @mcp.tool()
    async def integration_search(
        kind: Annotated[str, Field(description="Integration kind: 'gmail', 'slack', or 'discord'")],
        query: Annotated[str, Field(description="Search query (Gmail search syntax, Slack/Discord text filter)")],
        k: Annotated[int, Field(ge=1, le=50, description="Max results")] = 10,
    ) -> dict[str, Any]:
        """Live-search the connected Gmail/Slack/Discord account (not memory recall).

        Returns raw hits from the provider (message id, snippet, from/subject for
        Gmail; text + channel for Slack/Discord). Reads do not ingest; use
        ``integration_read`` to fetch + persist a message for future recall.
        """
        state = get_state()
        principal = await _principal()
        ctx = _integration_ctx(principal)
        connector_id = await _resolve_integration(state, principal, kind)
        hits = await state.services.connectors.search(
            ctx, connector_id, query=query, max_results=k,
        )
        return {"kind": kind, "query": query, "hits": hits}

    @mcp.tool()
    async def integration_read(
        kind: Annotated[str, Field(description="Integration kind: 'gmail', 'slack', or 'discord'")],
        message_id: Annotated[
            str,
            Field(
                description=(
                    "Message id (Gmail) or 'channel:ts' (Slack) or "
                    "'channel_id:message_id' (Discord) to fetch"
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Fetch one message/thread from the connected Gmail/Slack/Discord account.

        Also ingests the message body as a semantic memory (source='connector')
        so it is recallable from the shared brain in future turns.
        """
        state = get_state()
        principal = await _principal()
        ctx = _integration_ctx(principal)
        connector_id = await _resolve_integration(state, principal, kind)
        bundle = await state.services.connectors.refresh_if_needed(ctx, connector_id)
        if bundle is None:
            raise ValueError("integration has no stored credential")
        conn = await state.services.connectors.get_connector(ctx, connector_id)
        if conn is None:
            raise ValueError("connector not found")
        from teamshared.connectors.adapters import (
            DiscordConnector,
            GmailConnector,
            SlackConnector,
        )
        from teamshared.connectors.registry import build_connector

        adapter = build_connector(conn["kind"], conn["config"])
        token = state.services.connectors.api_token(conn["kind"], bundle)
        if isinstance(adapter, GmailConnector):
            msg = await adapter.get_message(token, message_id)
            content = (
                f"From: {msg.get('from','')}\nSubject: {msg.get('subject','')}\n\n{msg.get('body','')}"
            )
            await state.services.ingestion().ingest(
                ctx, content, kind="note", scope="org", visibility="shared",
                subject=msg.get("subject") or "gmail message",
                source="connector",
                source_ref={"connector_id": str(connector_id), "external_id": message_id},
            )
            return {"kind": "gmail", "message": msg}
        if isinstance(adapter, SlackConnector):
            channel, ts = message_id.split(":", 1) if ":" in message_id else (message_id, "")
            replies = await adapter.list_thread_replies(token, channel, ts) if ts else []
            return {"kind": "slack", "channel": channel, "thread": replies}
        if isinstance(adapter, DiscordConnector):
            msg = await adapter.get_message(token, message_id)
            content = (
                f"From: {msg.get('author','')}\nChannel: {msg.get('channel','')}\n\n"
                f"{msg.get('content','')}"
            )
            await state.services.ingestion().ingest(
                ctx, content, kind="note", scope="org", visibility="shared",
                subject=f"discord:{msg.get('channel') or 'message'}",
                source="connector",
                source_ref={"connector_id": str(connector_id), "external_id": message_id},
            )
            return {"kind": "discord", "message": msg}
        raise ValueError(f"read not supported for kind {kind!r}")

    @mcp.tool()
    async def integration_send(
        kind: Annotated[str, Field(description="Integration kind: 'gmail', 'slack', or 'discord'")],
        body: Annotated[str, Field(description="Message body / text to send")],
        to: Annotated[
            str | None,
            Field(description="Recipient email (gmail only)"),
        ] = None,
        subject: Annotated[
            str | None,
            Field(description="Email subject (gmail only)"),
        ] = None,
        channel: Annotated[
            str | None,
            Field(
                description=(
                    "Slack/Discord channel name/id; defaults to connector config"
                )
            ),
        ] = None,
        thread_id: Annotated[
            str | None,
            Field(description="Gmail threadId to reply in (gmail only)"),
        ] = None,
        thread_ts: Annotated[
            str | None,
            Field(
                description=(
                    "Slack parent message ts, or Discord thread channel id, for a reply"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Send an email (gmail) or post a Slack/Discord message via the connected account.

        Bidirectional: the outgoing action is audited and logged as an episodic
        timeline event ("sent email to X" / "posted in #channel").
        """
        state = get_state()
        principal = await _principal()
        ctx = _integration_ctx(principal)
        connector_id = await _resolve_integration(state, principal, kind)
        return await state.services.connectors.send(
            ctx, connector_id, kind=kind, to=to, subject=subject, body=body,
            channel=channel, thread_id=thread_id, thread_ts=thread_ts,
        )


def _resolve_dependency_ids(
    *,
    blocker_id: str | None,
    blocked_id: str | None,
    work_id: str | None,
    depends_on_id: str | None,
) -> tuple[str, str]:
    """Coalesce the canonical and alias spellings of a work dependency pair."""
    blocker = blocker_id if blocker_id is not None else depends_on_id
    blocked = blocked_id if blocked_id is not None else work_id
    if blocker is None or blocked is None:
        raise ValueError(
            "pass blocker_id + blocked_id (or the aliases depends_on_id + work_id)"
        )
    return blocker, blocked


def _serialize_procedure(proc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(proc)
    if "id" in out:
        out["id"] = str(out["id"])
    if "org_id" in out and out["org_id"] is not None:
        out["org_id"] = str(out["org_id"])
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out


def _serialize_skill(skill: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(skill)
    if "id" in out:
        out["id"] = str(out["id"])
    if "org_id" in out and out["org_id"] is not None:
        out["org_id"] = str(out["org_id"])
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out
