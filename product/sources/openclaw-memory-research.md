---
type: research
title: "OpenClaw native memory — file-based agent memory research"
author: OpenClaw (public docs)
origin: https://docs.openclaw.ai/concepts/memory
captured: 2026-07-12
note: >
  External product/architecture research from OpenClaw public docs (memory overview,
  dreaming, memory-wiki plugin). Vendor documentation only — no hands-on install,
  no user interviews. OpenClaw native memory is *personal-agent, workspace-local
  markdown* — not a multi-tenant org brain. GBrain/Cognee/TeamShared compete for
  the external MCP brain slot on the same harness.
---

# OpenClaw native memory — research

Captured 2026-07-12 from [OpenClaw memory overview](https://docs.openclaw.ai/concepts/memory),
[Dreaming](https://docs.openclaw.ai/concepts/dreaming), and
[memory-wiki plugin](https://docs.openclaw.ai/plugins/memory-wiki).

OpenClaw's category: **harness-native personal agent memory** — plain Markdown
files in the agent workspace (`~/.openclaw/workspace` by default). The model only
remembers what gets saved to disk; there is no hidden state. External MCP brains
(GBrain, Cognee, TeamShared) plug into the same OpenClaw runtime via
`mcp_servers.*` config.

## Positioning

> "OpenClaw remembers things by writing plain Markdown files in your agent's
> workspace (default `~/.openclaw/workspace`). The model only remembers what gets
> saved to disk; there is no hidden state."

> "If you want your agent to remember something, just ask it: 'Remember that I
> prefer TypeScript.' It writes the note to the appropriate file."

Compared to TeamShared: OpenClaw native memory does not pitch multi-tenant org
scoping, RLS, work queues, OTP console, or server-side capture middleware — it
pitches **git-friendly markdown SOtR**, bootstrap injection, hybrid search, and
optional background promotion (dreaming).

## Three memory files (core model)

| File | Role |
|------|------|
| `MEMORY.md` | Long-term memory — durable facts, preferences, decisions. Loaded at session start. |
| `memory/YYYY-MM-DD.md` | Daily notes — running context and observations. Indexed for search; not always injected. |
| `DREAMS.md` (optional) | Dream Diary and dreaming sweep summaries for human review |

From docs:

> "`MEMORY.md` is the compact, curated layer: durable facts, preferences, standing
> decisions, and short summaries that should be available at the start of a
> session. It is not a raw transcript, daily log, or exhaustive archive."

> "`memory/YYYY-MM-DD.md` files are the working layer: detailed daily notes,
> observations, session summaries, and raw context that may still be useful
> later. These are indexed for `memory_search` and `memory_get`, but are not
> injected into the bootstrap prompt on every turn."

TeamShared analogue: `MEMORY.md` ≈ semantic curated facts; daily notes ≈ working
memory → distiller → episodic; `DREAMS.md` ≈ curator/dreaming review surface.

## Bootstrap budget and truncation

> "If `MEMORY.md` grows past the bootstrap file budget, OpenClaw keeps the file on
> disk intact but truncates the copy injected into context."

Signal to move detail into `memory/*.md` or raise bootstrap limits. TeamShared
has no always-injected compact layer unless clients call `memory_assemble_context`
or follow the `teamshared.mdc` recall rule.

## Memory tools (active plugin)

Default plugin: `memory-core`. Agent tools:

| Tool | Purpose |
|------|---------|
| `memory_search` | Semantic + keyword hybrid search across indexed notes |
| `memory_get` | Read a specific memory file or line range |

> "When an embedding provider is configured, `memory_search` uses hybrid search:
> vector similarity (semantic meaning) combined with keyword matching (exact
> terms like IDs and code symbols)."

Default backend: SQLite (`memory-core`). Alternatives: QMD, Honcho, LanceDB —
plugin-swappable without forking the harness.

## Action-sensitive memories

OpenClaw documents memories that affect *when* the agent should act, not just
facts:

> "Capture that action boundary when a note involves: approval or permission
> requirements, temporary constraints, handoffs to another session, thread, or
> person, expiry conditions, safe-to-act timing, source or owner authority,
> instructions to avoid a tempting action."

> "Memory can preserve approval context, but it does not enforce policy. Use
> OpenClaw approval settings, sandboxing, and scheduled tasks for hard
> operational controls."

TeamShared: guarded ingestion + RBAC enforce some policy server-side; approvals
console UI partially deferred.

## Inferred commitments (short-lived follow-ups)

> "Commitments are opt-in, short-lived follow-up memories for that case. OpenClaw
> infers them in a hidden background pass, scopes them to the same agent and
> channel, and delivers due check-ins through heartbeat."

Durable facts stay in `MEMORY.md`; exact reminders use scheduled tasks. TeamShared
`work_*` covers assignable tasks but has no inferred commitment layer.

## Automatic memory flush (compaction hook)

> "Before compaction summarizes your conversation, OpenClaw runs a silent turn
> that reminds the agent to save important context to memory files. This is on by
> default."

Prevents context loss when conversation is summarized. TeamShared analogue:
`context_commit`, `context_prepare`, MCP middleware — server-side, not
"write markdown before summarize."

## Dreaming (background promotion)

Opt-in, disabled by default. Three phases per sweep: light → REM → deep.

> "Deep ranks candidates with weighted scoring and threshold gates (`minScore`,
> `minRecallCount`, `minUniqueQueries` must all pass)."

> "Long-term promotion still writes only to `MEMORY.md`."

Human review in `DREAMS.md`; shadow trials are report-only (never promote by
themselves). CLI: `openclaw memory promote`, `promote-explain`, `rem-harness`.

TeamShared: distiller worker (session → durable pillars) + curator (subject →
wiki). Dreaming has more explicit scoring transparency; TeamShared has richer
multi-pillar routing and org scope.

## memory-wiki plugin (belief layer)

Bundled plugin — does **not** replace the active memory plugin:

> "`memory-wiki` does not replace the active memory plugin. Recall, promotion,
> indexing, and dreaming stay owned by whichever memory backend is configured."

Adds compiled wiki vault with structured claims, evidence, contradiction/stale
dashboards, and tools: `wiki_status`, `wiki_search`, `wiki_get`, `wiki_apply`,
`wiki_lint`.

Vault modes: `isolated` (default), `bridge` (reads public artifacts from active
memory plugin), `unsafe-local`. Per-agent vault scope available (`vault.scope:
agent`) — same-process knowledge boundary, not OS security boundary.

> "Claims can be tracked, scored, contested, and resolved back to sources."

TeamShared peer: curator `wiki_pages` + ontology console + `memory_entity_view`
— server-managed, org-scoped, not per-agent markdown vault.

## Relationship to external MCP brains

OpenClaw is the **harness** (sessions, compaction, heartbeat, plugins). GBrain
is positioned as the production brain behind OpenClaw/Hermes (`gbrain-competitor-research.md`).
TeamShared wires in via `install.sh` (`openclaw` agent type):

- `mcp_servers.teamshared.url` + bearer token
- Optional gateway provider for pre-LLM compression + enrichment

Native `memory-core` and external MCP memory can coexist: local scratch +
org-wide durable brain — requires documented precedence to avoid duplicate facts.

## Tier classification (synthesis)

| Tier | Fit |
|------|-----|
| Tier 1 company brain | **No** — personal/workspace file memory |
| Tier 2 hosted MCP memory | **No** — local files + optional plugins |
| Tier 3 harness-adjacent | **Yes** — default solo-agent memory layer on OpenClaw harness |
| Distribution channel | **Yes** — OpenClaw is where GBrain/Cognee/TeamShared compete for MCP slot |

Fits **Tier 3 — harness-native personal memory** alongside mex (repo scaffold)
but richer (search, dreaming, memory-wiki). Not a multi-tenant org brain.

## TeamShared overlap / complement

**Overlap:** session amnesia, durable facts, working→long-term promotion,
hybrid search, wiki/knowledge layer, action-boundary notes.

**TeamShared-only:** multi-tenant RLS, cross-agent shared recall, work queue,
OKRs, OTP console, server-side capture, `memory_think` synthesis path,
`context_*` compression as MCP service.

**OpenClaw-only:** always-bootstrap `MEMORY.md`, git-reviewable workspace files,
dreaming scored promotion CLI, commitments + heartbeat, plugin backend swap
(SQLite/QMD/Honcho/LanceDB), memory-wiki claims/evidence dashboards.

**Complement pattern:** OpenClaw `MEMORY.md` for machine-local bootstrap;
TeamShared MCP for org brain. Risk: two SOtRs writing the same facts without
precedence rules.

## Gaps in this corpus

- No % of OpenClaw users on native memory vs GBrain vs TeamShared MCP.
- No recall benchmark (OpenClaw SQLite hybrid vs TeamShared pgvector).
- No design-partner interviews with OpenClaw homelab operators.
- memory-wiki adoption and maturity vs TeamShared curator unmeasured.

## Sources

- https://docs.openclaw.ai/concepts/memory
- https://docs.openclaw.ai/concepts/dreaming
- https://docs.openclaw.ai/plugins/memory-wiki
- Internal: `shipped-state-2026-07-12.md`, `gbrain-competitor-research.md`
