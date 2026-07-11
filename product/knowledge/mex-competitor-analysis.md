# mex competitor analysis (mogkit)

Generated via mogkit workflow: source capture → `discovery-query` (×3) →
`tradeoff-frame`. Source: `product/sources/mex-research.md` (public README,
launchx.page, GitHub issues/PR #84, npm metadata). Corpus health: **thin**
(single-source vendor/marketing research — no user interviews, no hands-on
`mex setup` run in this corpus).

---

## Executive summary

**mex is not a TeamShared replacement — it is a repo-scoped context scaffold
with a drift-detection CLI.** Where TeamShared persists org-scoped durable
knowledge (semantic, episodic, procedural pillars, distillation, wiki), mex keeps
*this repository's* agent instructions honest: routed markdown files, an
append-only decision log, and eleven zero-token checkers that catch when docs
lie about paths, scripts, and dependencies.

The overlap is real but narrow: both target **agent amnesia** and both are
moving toward **MCP tool surfaces** for Cursor/Claude Code. They diverge on
**scope** (single repo git-local vs multi-tenant shared brain), **memory shape**
(routed markdown scaffold vs vector+SQL pillars), and **freshness model**
(deterministic drift score vs distiller/curator LLM workers).

For TeamShared product planning: mex addresses **"this repo's conventions are
stale or bloated"** and **"load only the context the task needs"** — not
**"what did the team decide across repos last month."** The interesting
question is whether TeamShared should **complement mex** (org brain + per-repo
scaffold) or **borrow its drift-detection thesis** for `AGENTS.md` / plugin
rules — not whether to compete on markdown routing inside each checkout.

---

## discovery-query #1: What problem does mex solve?

### Findings

**1. Context flooding from monolithic rules files**
- *Confidence: Multi-source (README + launchx.page)*
- "Most agent memory setups become one giant instruction file… floods the context window, burns tokens" — `mex-research.md`
- mex replaces dump with: tiny anchor → `ROUTER.md` → task-specific `context/` + `patterns/` files
- TeamShared ships a global `teamshared.mdc` rule + MCP recall; repo facts live in durable memory with optional `repo=` tags — different mechanism, same "don't dump everything" pressure.

**2. Silent doc drift — scaffold claims diverge from codebase**
- *Confidence: Multi-source*
- Eleven deterministic checkers (paths, commands, deps, staleness, broken links) — README
- "`mex check`… Zero tokens, zero AI" — README
- TeamShared has no equivalent linter for AGENTS.md / plugin rules vs live repo; distiller captures *conversation* truth, not *instruction file* truth.

**3. Cold starts per repo session**
- *Confidence: Single-source*
- "Every session starts cold" — launchx.page
- mex boot: load ~120-token anchor → route to relevant files
- TeamShared boot: MCP `memory_recall` / session logging — org memory, not automatic repo architecture ingest.

**4. Token economics as explicit product wedge**
- *Confidence: Single-source (vendor benchmark)*
- "~60% average token reduction per session" — README (OpenClaw homelab community test)
- LaunchX site cites 56–68% reductions on homelab scenarios; independent Next.js SaaS numbers on marketing page (unverified)
- TeamShared optimizes via context compression middleware (`context_normalize`, SmartCrusher) on tool output — not on repo instruction routing.

**5. Persistent-agent mode extends beyond code repos**
- *Confidence: Single-source*
- `mex setup --mode agent-memory` + `HEARTBEAT.md` + interval `mex watch` — README
- 10/10 OpenClaw homelab scenarios cited — operational runbooks, not application code
- Overlaps TeamShared's continual-learning / session logging for long-running agents, but mex stores runbooks in git markdown, not Redis/Postgres pillars.

### Gaps

- No hands-on validation that mex drift checkers catch real-world stale `AGENTS.md` in TeamShared's own repo.
- Token reduction claims are vendor/community-sourced; no A/B vs TeamShared `memory_assemble_context`.
- Unknown adoption: npm download volume, % of Cursor users running mex alongside cloud memory.
- `mex sync` quality (AI fix loop) unbenchmarked — drift detection is deterministic; repair is not.

### Discovery questions

1. When your agent gets repo context wrong, is the failure stale *rules files* or missing *team knowledge*?
2. Would you run `mex check` in CI if it gated merges on drift score?
3. Do you want memory in git (reviewable PRs) or in a brain server (recall/think)?
4. For persistent agents (OpenClaw), is heartbeat + markdown enough vs distillation to episodic memory?

---

## discovery-query #2: How does mex relate to TeamShared?

### Findings

**1. Orthogonal layers — repo scaffold vs org brain (same pattern as Headroom/Screenpipe)**
- *Confidence: Single-source (synthesis)*
- mex: per-repo `.mex/` markdown + local jsonl events
- TeamShared: org-scoped pillars, bearer auth, shared recall across agents
- Both reduce amnesia; mex from *structured repo docs*, TeamShared from *durable team memory*.

**2. Tier 3 landscape neighbor — not GBrain-class company brain**
- *Confidence: Multi-source (landscape doc + mex research)*
- shared-brain-landscape-2026.md Tier 3: "Git-native / repo-scoped memory" (xChuCx/agent-memory cited; mex fits same shelf)
- mex: 1.1k★ vs GBrain 23k★; no synthesis, graph, multi-user OAuth, or company-brain tutorial
- TeamShared competes in Tier 1–2; mex competes for *Cursor rules budget* not *org memory budget*.

**3. Conceptual collision: patterns/ vs skills/playbooks**
- *Confidence: Single-source*
- mex `patterns/` — task guides with gotchas + verify steps
- TeamShared `memory_skill_set` / `memory_playbook_set` — versioned org-wide skills in Postgres
- Same *atomic how-to* thesis; mex is repo-local git markdown, TeamShared is shared brain with MCP authoring.

**4. MCP collision incoming — five tools vs ~70**
- *Confidence: Single-source (draft PR)*
- mex-mcp (draft): `mex_check`, `mex_log`, `mex_timeline`, `mex_heartbeat`, `mex_read_file`
- TeamShared MCP: `memory_recall`, `memory_remember`, `memory_session_*`, `work_*`, etc.
- Session boot could be: `mex_read_file("ROUTER.md")` + `memory_recall(query=…)` — complementary if both installed; confusing if agents don't know which to call.

**5. TeamShared already documents repo-scoped memory — mex productizes the git side**
- *Confidence: Single-source (internal)*
- TeamShared `repo=` / `github=` tags soft-boost recall; `AGENTS.md` in repo is team convention
- mex productizes: ROUTER, drift checkers, tool-specific anchor files, decision jsonl
- Risk: buyers conflate "install teamshared plugin" with "run mex setup" — both claim to fix agent memory.

**6. LaunchX monetization vs TeamShared unpublished pricing**
- *Confidence: Single-source*
- LaunchX sells boilerplates with mex pre-baked — OSS wedge + paid templates
- TeamShared: hosted teamshared.com, no published tier table in corpus
- Different GTM: mex → individual dev / template buyer; TeamShared → org admin + API keys.

### Gaps

- No documented integration path (mex decision jsonl → TeamShared episodic ingest).
- Unknown whether mex maintainers view cloud brains as partners or replacements.
- TeamShared plugin does not run drift detection on installed `teamshared.mdc` vs server rule version.
- If mex-mcp ships, do Cursor users drop TeamShared for repo-only workflows?

### Discovery questions

1. For a 10-person eng team, is memory mostly *shared decisions* or *per-repo conventions*?
2. Would you commit `.mex/` to git and still pay for org-scoped recall?
3. Should `memory_remember(kind=fact)` auto-update mex `context/decisions.md`, or stay separate?
4. Does drift score belong in TeamShared console for repos linked to an org?

---

## discovery-query #3: What is mex's technical moat?

### Findings

**1. Deterministic drift detection without LLM cost**
- *Confidence: Multi-source*
- 11 checkers, scored report, `--json` for automation — README
- Unique in landscape corpus: neither GBrain, Mem0, nor TeamShared lints instruction files against live manifests
- Moat is *engineering on static analysis*, not retrieval quality.

**2. Context routing protocol (ROUTER.md contract)**
- *Confidence: Single-source*
- Explicit task-type → file mapping; agent loads subset not monolith
- Similar to GBrain `skills/RESOLVER.md` routing, but repo-scoped and drift-checked
- TeamShared has no first-class routing table for MCP recall scopes per task type.

**3. Sync loop targets only stale files**
- *Confidence: Single-source*
- "`mex sync` builds targeted prompts so the agent fixes only the stale pieces" — README
- Contrast TeamShared distiller: processes whole session transcripts → facts
- mex repair is *doc maintenance*; TeamShared repair is *knowledge extraction*.

**4. Tool-native anchor files**
- *Confidence: Single-source*
- Generates `CLAUDE.md`, `.cursorrules`, etc. with identical content — setup flow
- TeamShared installs global rule via `install.sh`; mex generates per-repo anchors
- mex meets developers where their harness reads config; TeamShared adds MCP layer on top.

**5. Event log as lightweight episodic substitute**
- *Confidence: Single-source*
- `.mex/events/decisions.jsonl` via `mex log` — append-only, local
- TeamShared episodic pillar: distilled sessions, org-visible, searchable
- mex events don't cross agents unless committed to git; TeamShared events are org-scoped by default.

### Gaps

- Drift checkers only understand npm-centric manifests today (pyproject/go.mod on roadmap — issue #3).
- `mex sync` AI fix quality and false-positive rate unknown.
- MCP server still draft — moat unrealized until `mex-mcp` publishes to npm.
- No federation story (cf. agent-memory landscape stores) for cross-repo system maps.

---

## tradeoff-frame: How should TeamShared relate to mex?

### The decision

Should TeamShared treat mex as a complementary repo layer, absorb drift-detection
into the plugin/console, or ignore it as a single-repo tool outside the org-brain
buyer?

**Options:**
- **A.** Complementary — document dual setup: mex per repo + TeamShared for org memory; no integration
- **B.** Integrate — mex `decisions.jsonl` / pattern updates → TeamShared episodic ingest webhook
- **C.** Build drift detection — `teamshared check` lints AGENTS.md + plugin rule vs repo manifests (borrow mex thesis)
- **D.** Compete on repo routing — ship TeamShared repo scaffold templates + MCP read_file equivalents
- **E.** Ignore — mex is Tier 3 git tooling; stay focused on org brain vs GBrain/Hivemind

### Real axes

1. **Buyer mental model** — "fix my CLAUDE.md" (mex) vs "give my team a brain" (TeamShared)
2. **Source of truth** — git-committed markdown vs Postgres/Mem0 pillars
3. **Freshness** — deterministic lint (mex) vs LLM distillation (TeamShared)
4. **MCP surface area** — agents already struggle with tool overload; adding mex-mcp increases choice complexity
5. **Engineering cost** — drift checkers are a product vertical (11+ checkers, cross-ecosystem manifests)

### Option profiles

**A — Complementary (status quo+)**
- Optimizes: clearest positioning; mex owns repo hygiene, TeamShared owns org recall
- Sacrifices: no unified query; duplicate decision logging if agents use both `mex_log` and `memory_remember`

**B — Ingest connector**
- Optimizes: repo decisions land in org episodic timeline; humans see mex events in console
- Sacrifices: sync model, conflict resolution when git and cloud disagree; mex stays local-first

**C — Drift detection in plugin**
- Optimizes: TeamShared-branded `AGENTS.md` / rule freshness; differentiator vs GBrain cloud brain
- Sacrifices: quarters of static-analysis work; overlaps mex OSS; may be better to depend on mex-mcp

**D — Repo routing product**
- Optimizes: single vendor for repo + org memory
- Sacrifices: competes with focused OSS tool; distracts from multi-tenant moat; mex already ships patterns/ROUTER

**E — Ignore**
- Optimizes: focus on GBrain/Hivemind/Mem0 tier; mex is <2k★ repo tool
- Sacrifices: ignores MCP boot collision; leaves "stale rules file" pain unaddressed in TeamShared story

### Reversibility

**Two-way door** for A and B (docs/connectors optional).
**One-way door** for C and D (product commitments + maintenance burden).
E is reversible but may cede the repo-scaffold narrative to mex + LaunchX.

### Decisive evidence

- Interview: do design partners run mex, Cursor rules, or only TeamShared MCP for repo context?
- Metric: what % of `memory_remember` facts duplicate content already in repo AGENTS.md / mex scaffold?
- Experiment: run `mex check` on teamshared repo — does drift score correlate with bad agent sessions?
- Ship watch: when `mex-mcp` publishes, measure npm installs vs TeamShared plugin installs (if available).

Frame the decision. Then make the call yourself, or escalate to whoever owns it.

---

## Comparison matrix (mex vs TeamShared vs GBrain vs xChuCx/agent-memory)

| Dimension | mex | TeamShared | GBrain | agent-memory (Go) |
|---|---|---|---|---|
| **Primary scope** | Single repo | Multi-tenant org | Personal → company brain | Single repo (+ federation) |
| **Storage** | Git markdown + jsonl | Postgres + Redis + Mem0 | Git brain repo + Postgres sync | Git markdown |
| **Query** | Read routed files / upcoming MCP | MCP recall/think | MCP search/think + gaps | 3 MCP tools + CLI |
| **Freshness** | 11 drift checkers (no AI) | Distiller + curator LLM | Dream cycle + graph | Human review gate |
| **Skills/how-to** | `patterns/` markdown | Skills + playbooks pillar | 43 skillpack skills | Per-module facts in MD |
| **Cross-agent** | Git commit/share | Native shared brain | OAuth-scoped slices | Federation to landscape repos |
| **Token story** | Route, don't dump (~60% claimed) | Context compression middleware | Synthesis + chunk retrieval | MCP-in, structured-out |
| **Human surface** | CLI/TUI dashboard | Console wiki + work | Agent-query optimized | CLI review --diff |
| **Secrets** | Not emphasized | Write-time guards | Self-hosted trust | Secret scan before write |
| **License** | MIT | (teamshared) | MIT | (check repo) |
| **Stars (Jun 2026)** | ~1.1k | — | ~23k | smaller |
| **Moat** | Drift detection + routing | Multi-tenant governance + pillars | Synthesis + graph + distribution | Branch-aware git + review |

---

## Recommended product responses (not mogkit output — engineering judgment)

1. **Classify mex as Tier 3 repo-scoped adjacent**, not memory competitor #2 — tag
   `repo-scaffold` in graph alongside xChuCx/agent-memory; same shelf as Headroom
   (orthogonal layer), different axis (git docs vs compression vs capture).
2. **Publish complementary positioning** — "mex for repo hygiene, TeamShared for
   team recall" in plugin docs; avoid claiming TeamShared replaces ROUTER/patterns.
3. **Watch mex-mcp launch** — when `mex_read_file` + `mex_check` ship, add a short
   "dual MCP boot" note: repo orientation (mex) then org recall (TeamShared).
4. **Spike Option C lightly** — compare `mex check` output on teamshared repo vs
   pain from stale `AGENTS.md`; if high signal, integrate via mex-mcp dependency
   rather than rebuilding 11 checkers.
5. **Do not build Option D** unless a design partner pays — mex + LaunchX own repo
   scaffold; TeamShared wins on org brain, work queue, approvals, strategic memory.
6. **Address duplication in agent guidance** — plugin rule should say: use
   `memory_remember` for *team-durable* facts; use repo docs / mex for *codebase
   conventions*; don't store architecture diagrams in cloud if they belong in
   `context/architecture.md`.
7. **Optional B for decisions** — if users already `mex log` decisions, a git-hook
   → episodic webhook could enrich timeline without owning drift detection.

---

## Files touched

- `product/sources/mex-research.md` — new research source
- `product/knowledge/mex-competitor-analysis.md` — this document

Answer your question from the findings. Fill the gaps before you commit to positioning.

---

## Next mogkit steps

1. Re-run `graphify` to ingest `mex-research.md` into `product/graph/graph.json`.
2. `discovery-query`: "Do buyers conflate repo scaffold tools with company brain?"
3. `interview-guide` — validate mex vs TeamShared split for 5–20 person eng teams.
4. Hands-on: run `npx mex-agent setup` on teamshared repo; capture drift score + token diff as user evidence.
5. `spec-stress-test` — if pursuing Option B, red-team mex jsonl → episodic ingest path.
