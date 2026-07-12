---
type: doc
---

# TeamShared shipped state — 2026-07-12

Canonical description of what is **built and shipping** in this repository today.
For roadmap and aspirational phases, see `prod-plan.md`. For engineering
conventions, see `AGENTS.md`.

## Product thesis

TeamShared is a **shared agent memory MCP server** for engineering teams. Humans
administer the brain through a web console at `/app`; agents read and write
through bearer-token MCP tools (`tsk_*` API keys). Durable recall is **shared
across agents by default** on semantic, episodic, procedural, skill, strategic,
and work pillars — working memory stays per-session.

## Memory pillars (six + optional graph)

| Pillar | Storage | Purpose |
|--------|---------|---------|
| **Working** | Redis | Per-session conversation buffer; distilled on close |
| **Semantic** | Postgres + pgvector | Facts, preferences, notes |
| **Episodic** | Postgres + pgvector | Distilled session timeline and events |
| **Procedural** | Postgres | Versioned **skills** (atomic) and **playbooks** (composed flows) |
| **Strategic** | Postgres | Vision, mission, purpose, OKR cycles |
| **Work** | Postgres | Org task queue with projects, dependencies, followers |
| **Graph** (optional) | Neo4j | Explicit entity relationships (`memory_graph_*`) |

## MCP surface (high level)

- **Recall & synthesis:** `memory_recall`, `memory_think`, `memory_assemble_context`, `memory_entity_view`
- **Writes:** `memory_remember`, `memory_skill_set`, `memory_playbook_set`, `memory_strategic_*`, `work_*`, `project_*`
- **Session logging:** `memory_session_ensure`, `memory_session_append`, `context_commit`
- **Context compression:** `context_compress`, `context_prepare`, `context_normalize`, `context_retrieve` (CCR refs)
- **Ontology:** `memory_ontology_list`, `memory_ontology_propose_entity`, `memory_action_apply`
- **Client state:** `memory_state_get` / `memory_state_set` (token+repo scoped bookkeeping)
- **Ops:** `health`, `version`, `memory_tools_catalog`

Server middleware auto-normalizes bulky MCP responses and logs tool calls to a
rolling autosession when capture is enabled.

## Workers

- **Distiller** — consumes Redis queue; LLM summarizes closed sessions into durable memory
- **Curator** — debounced queue; (re)synthesizes human-readable `wiki_pages` articles per subject

## Human console (`/app`)

OTP email sign-in (no password). Self-service: any email provisions a private org;
admins add teammates to share a team brain. Multi-org accounts with header org switcher.

| Section | Path | Notes |
|---------|------|-------|
| Home | `/app` | Brain health, open work, recent audit |
| Work | `/app/work` | Task queue; assign to people or agents |
| Projects | `/app/projects` | Asana-style boards with sections |
| Strategy | `/app/strategy` | Vision, mission, OKRs |
| Wiki | `/app/wiki` | Curated topic pages + timeline + playbooks |
| Memory explorer | `/app/memory` | Keyword search + **Ask the brain** (`memory_think`) |
| Skills | `/app/skills` | Atomic how-tos |
| Playbooks | `/app/playbooks` | Compose skills into flows |
| Ontology | `/app/ontology` | Entity types, link types, governed actions |
| People | `/app/people` | Add member by email, RBAC roles |
| Orgs | `/app/orgs` | Create and switch orgs |
| API keys | `/app/keys` | Mint/revoke `tsk_*` keys (shown once) |
| Audit | `/app/audit` | Memory and admin actions |
| Settings | `/app/settings` | System status, export, purge |

There is **no** `/app/approvals` console route today. Guarded ingestion and
`pending_approval` status exist in the data model; strategic proposals reference
approvals in copy but the review queue UI is not shipped.

## Public surfaces

| Path | Audience |
|------|----------|
| `/` | Landing page + invite token redemption |
| `/install` | One-command agent onboarding (`install.sh`) |
| `/memory` | Public memory status dashboard (no auth) |
| `/login` | OTP sign-in → console |
| `/mcp` | MCP HTTP endpoint |
| `/health` | Dependency health |

## Agent onboarding

- Unified `curl -fsSL https://teamshared.com/install.sh | bash`
- Cursor plugin bundles MCP wiring, recall rule, continual-learning hooks
- Bearer token inline in MCP client config (not env vars)
- Agent types: `cursor`, `codex`, `hermes`, `claude`, `openclaw`, `pi`

## Capture & compression

- **Server-side:** `ToolCallCaptureMiddleware` records MCP tool calls per agent
- **Agent-side:** `memory_session_*` + `context_commit` per the `teamshared.mdc` rule
- **Gateway (opt-in):** `POST /gateway/v1/chat/completions` runs pre-LLM compression + enrichment for harnesses with custom base URLs
- **Headroom-class problem:** solved in-product via MCP `context_*` tools and middleware — no separate proxy required

## Multi-tenancy & security (shipped)

- `org_id` + Postgres RLS on all tenant data
- Global `accounts` table; per-org `users` + RBAC (`org:admin`, etc.)
- Bearer `tsk_*` keys bound to org; `PrincipalResolver` on every MCP call
- Secure retrieval: permission checks before vector search
- Rate limits, signed queue jobs, audit log for reads/writes
- Stages 0–4 of `prod-plan.md` marked **Done** (multi-tenant, RLS, guarded ingestion)

## Not shipped (roadmap / aspirational)

- SSO/SAML/SCIM, SOC 2, data residency
- External connectors (Slack, GitHub, Notion, Linear, …) as first-class sync
- Human approvals console for agent writes
- Consent-first client capture gate (removed 2026-06-19; server-side capture is default when enabled)
- Bi-temporal fact validity (Graphiti-style point-in-time queries)
- Auto-trace-to-skill mining (Hivemind-style)

## Competitive positioning (from shipped differentiation)

TeamShared differentiates on **governance + team workflow**, not raw graph depth:

- Cross-agent shared recall by default (vs per-dataset isolation)
- Work queue + projects + strategic OKRs in the same brain
- Human console (wiki, ontology, memory explorer) alongside MCP
- Skills/playbooks as first-class procedural memory
- Context compression built into MCP (vs external Headroom proxy)
- Curated wiki pages (curator worker) vs raw record dumps

Primary Tier-1 memory competitors in corpus: **GBrain**, **Cognee**.
Adjacent: Headroom (compression), Screenpipe (desktop capture), mex (repo scaffold), RACT (coding harness).

## Engineering baseline

Clean-room activation run (`clean-room-run-2026-07-11.md`): migrations, RLS,
integration tests, and cross-agent recall smoke passed in ~10–11 minutes cold.
Does not substitute design-partner validation.
