# RACT competitor analysis (mogkit)

Generated via mogkit workflow: source capture → `discovery-query` (×3) →
`tradeoff-frame`. Source: `product/sources/ract-research.md` (public README,
docs/ARCHITECTURE.md, GitHub metadata). Corpus health: **thin**
(single-source vendor research — no user interviews, no hands-on `rootact --loop`
run in this corpus).

---

## Executive summary

**RACT is not a TeamShared replacement — it is a CLI-first agentic coding harness
with anti-rot verifiers and MCP consumer support.** Where TeamShared persists
org-scoped durable knowledge (semantic, episodic, procedural pillars,
distillation, wiki), RACT runs the *build loop* for one repo: plan → execute →
test → signed receipt, with Root Knot sentinels that halt unsigned drift.

The overlap is narrow but strategic: both address **agent amnesia** and both
integrate **MCP**. They diverge on **scope** (single-repo harness vs multi-tenant
shared brain), **primary buyer** (terminal sovereign coder vs org admin), and
**rot axis** (code duplication/dead code vs instruction-file drift / team facts).

For TeamShared product planning: RACT competes with **Cursor** (the harness TeamShared
plugs into), not with GBrain/Cognee. The interesting question is whether TeamShared
should be the **default org-memory MCP server** in RACT's `rootact.yaml` — not
whether to build a coding loop.

---

## discovery-query #1: What problem does RACT solve?

### Findings

**1. AI-assisted code rot (duplication, drift, dead code, undocumented logic)**
- *Confidence: Multi-source (README cites GitClear/GitKraken 623M-commit study)*
- Four rot vectors named explicitly; anti-rot verbs are first-class CLI, not plugins
- TeamShared distiller captures *conversation* knowledge; no equivalent for
  *codebase structural rot* (near-duplicate modules, unreachable files).

**2. Provider lock-in and subscription economics**
- *Confidence: Single-source (vendor comparison table)*
- Model-agnostic router: local + OpenAI + Anthropic + OpenRouter + others
- "Free to run locally; pay only for tokens you route" vs Cursor/Claude Code $20/mo
- TeamShared is memory infrastructure, not a coding subscription — orthogonal pricing.

**3. Unsigned agent output compounding across loop iterations**
- *Confidence: Multi-source (README + ARCHITECTURE.md)*
- `_ROOT_KNOT` sentinel stops recursion when generated files lack identity markers
- `SignatureGuardian` verifies markers across the tree
- TeamShared has write-time secret guards and approval queues for *memory writes*,
  not *code artifact continuity*.

**4. Opaque agent runs — need auditable receipts**
- *Confidence: Single-source*
- `rootact report --last --format json` — intent, model, steps, tests, quality score, cost
- Positioned as cross-provider leaderboard substrate
- TeamShared audit logs + episodic timeline serve org governance, not per-run engineering QA.

**5. IDE-coupled agents vs terminal-first sovereignty**
- *Confidence: Single-source (README positioning)*
- CLI-first, own your pipeline, surgical unified-diff application
- TeamShared ships Cursor plugin + MCP — assumes IDE/harness exists; doesn't replace it.

### Gaps

- No hands-on validation of Root Knot stopping real regressions in a TeamShared-sized repo.
- 3 GitHub stars — adoption and community feedback essentially unknown.
- PolyForm Noncommercial license may block commercial design partners evaluating RACT.
- Anti-rot verbs (`auction`, `consolidate`) quality unbenchmarked vs human review.

### Discovery questions

1. When your codebase degrades after agent sessions, is it *duplicate modules* or
   *stale team decisions*?
2. Would signed run receipts replace or complement TeamShared episodic distillation?
3. Do terminal-first developers want org memory inside the harness (RACT+MCP) or in the IDE (Cursor+TeamShared)?

---

## discovery-query #2: How does RACT relate to TeamShared?

### Findings

**1. Orthogonal layers — coding harness vs org brain (same pattern as mex/Headroom)**
- *Confidence: Multi-source (synthesis + ract-research taxonomy)*
- RACT: executes intents, writes code, loops with Progress Oracle
- TeamShared: recalls, remembers, distills, work queue, strategic memory
- RACT's `RetrievalAdapter` is keyword-local; org recall requires external MCP.

**2. Tier 3 adjacent harness — not Tier 1 memory competitor**
- *Confidence: Single-source (landscape placement in ract-research.md)*
- README compares to Cursor/Claude Code/Lovable, not GBrain/Cognee/Mem0
- ~3★ vs GBrain ~23k★ / Cognee ~27k★ — different category and scale
- TeamShared competes on org brain; RACT competes on *who runs the coding loop*.

**3. MCP relationship: consumer vs provider**
- *Confidence: Multi-source*
- RACT: `mcp_servers` in `rootact.yaml`, `McpToolRegistry`, `rootact mcp list`
- TeamShared: MCP *server* with `memory_recall`, `memory_remember`, `work_*`, etc.
- **Complementary wiring:** RACT plan steps can call TeamShared tools for org context
  before code generation — same dual-MCP pattern as mex-mcp + TeamShared.

**4. Skills collision — project templates vs org pillars**
- *Confidence: Single-source*
- RACT: built-in + marketplace JSON skill templates installed per project
- TeamShared: `memory_skill_set` / `memory_playbook_set` versioned in Postgres
- Same *atomic how-to* thesis; RACT is repo-local, TeamShared is shared brain.

**5. Anti-rot axis overlaps mex, not TeamShared core**
- *Confidence: Multi-source (mex + ract research)*
- mex: 11 drift checkers on *instruction scaffold* vs manifests
- RACT: consolidate/novelty/auction/fence on *code structure*
- TeamShared could benefit from *both* without building either — plugin docs should
  clarify division of labor.

**6. Cursor is the shared battlefield**
- *Confidence: Single-source (README)*
- RACT explicitly positions against Cursor; TeamShared plugin targets Cursor
- If RACT gains adoption, TeamShared needs an MCP config story for `rootact.yaml`,
  not just `~/.cursor/mcp.json`.

### Gaps

- No published RACT + TeamShared integration example or author endorsement.
- Unknown whether RACT retrieval adapter will grow into a full memory layer (competing).
- TeamShared plugin rule doesn't mention terminal harnesses (Codex CLI, RACT, Claude Code).

### Discovery questions

1. Would you run RACT for code loops and TeamShared for team recall in the same repo?
2. Should `memory_recall` results feed RACT's `--project-doc` automatically?
3. For a 10-person team, is the harness homogenous (all Cursor) or mixed (Cursor + CLI)?

---

## discovery-query #3: What is RACT's technical moat?

### Findings

**1. Root Knot as loop invariant (not just authorship branding)**
- *Confidence: Multi-source*
- Missing sentinel halts `--loop` recursion — safety property, not watermark
- No peer in corpus implements code-output continuity guard at this granularity
- Moat is *opinionated harness design*, not retrieval quality.

**2. Anti-rot CLI as product surface**
- *Confidence: Single-source*
- consolidate, novelty scan, auction, fence, whisper — named verbs with operator handshakes
- mex covers doc drift; RACT covers code rot — complementary static/structural analysis
- TeamShared has no first-class code hygiene CLI.

**3. Progress Oracle milestone loop**
- *Confidence: Multi-source (README + ARCHITECTURE.md)*
- Stops on completion, regression, or missing Root Knot — not turn count
- `HandshakeRegistry` queues high-risk milestones for async review
- Contrast TeamShared: session distillation is post-hoc; no milestone-driven code loop.

**4. Signed receipts as portable audit artifact**
- *Confidence: Single-source*
- JSON export designed for CI/scripts and cross-model comparison
- TeamShared episodic events are NL summaries — different grain for engineering QA.

**5. Model-agnostic provider router with capability scoring**
- *Confidence: Single-source*
- `CapabilityRegistry` + presets for local/OpenAI/Anthropic/etc.
- TeamShared uses LLM for distiller/curator only — not a coding provider router.

### Gaps

- Early stage (3★, PolyForm NC) — moat unproven in market.
- Mutation testing and coverage delta are local heavyweight diagnostics — not CI-gated yet.
- Kairos separation suggests upstream proprietary system may outpace public RACT.

---

## tradeoff-frame: How should TeamShared relate to RACT?

### The decision

Should TeamShared treat RACT as a complementary CLI harness (MCP consumer),
compete on coding-loop features, or ignore it as pre-PMF niche tooling?

**Options:**
- **A.** Complementary — document RACT + TeamShared MCP wiring in plugin docs; no code integration
- **B.** First-class harness — ship `rootact.yaml` snippet in install assets alongside Cursor MCP JSON
- **C.** Absorb receipt thesis — export structured run receipts from TeamShared session distillation
- **D.** Build anti-rot CLI — `teamshared code-check` borrowing auction/consolidate ideas for linked repos
- **E.** Ignore — RACT is Tier 3 harness; stay focused on org brain vs GBrain/Cognee

### Real axes

| Axis | RACT | TeamShared |
|------|------|------------|
| **Primary job** | Execute coding intents with quality gates | Persist and recall org knowledge |
| **Scope** | Single repo checkout | Multi-tenant org |
| **MCP role** | Consumer (`mcp_servers`) | Provider (`memory_*`, `work_*`) |
| **Rot fight** | Code structure (dupes, dead code) | Context rot + instruction drift (via mex adjacency) |
| **Audit** | Per-run signed JSON receipt | Episodic timeline + audit log |
| **Harness** | CLI (`rootact`) | Cursor plugin + generic MCP |
| **License** | PolyForm NC | (teamshared) |
| **Stars (Jul 2026)** | ~3 | — |
| **Moat** | Root Knot + anti-rot loop | Multi-tenant governance + pillars |

### Recommendation lean

**Option A now, Option B if a design partner uses RACT** — RACT is too early and
license-restricted to prioritize, but the MCP-consumer pattern validates TeamShared's
"USB-C for memory" thesis from the *other side* of the wire.

---

## Comparison matrix (landscape shelf)

| Dimension | RACT | TeamShared | mex | Cursor |
|-----------|------|------------|-----|--------|
| **Category** | Agentic coding CLI | Org memory MCP server | Repo scaffold + drift CLI | IDE agent |
| **Memory** | Keyword retrieval + optional MCP | Five pillars + distillation | Git markdown routing | Session + optional MCP |
| **Anti-rot** | Code-focused CLI verbs | None (mex adjacency for docs) | Doc drift checkers | None core |
| **Loop** | Progress Oracle milestones | Session distill on close | `mex watch` heartbeat | User-prompted turns |
| **MCP** | Consumer | Provider | Draft consumer (mex-mcp) | Consumer |
| **Skills** | Project marketplace JSON | Org skills/playbooks | `patterns/` markdown | Rules + skills |
| **Human gate** | Async handshakes | Approvals console + OTP | Review diff | Inline dialogs |
| **License** | PolyForm NC | — | MIT | Commercial |

---

## Recommended product responses (not mogkit output — engineering judgment)

1. **Classify RACT as Tier 3 adjacent harness**, not memory competitor — tag
   `agentic-coding-cli` in graph; same shelf as "competes with Cursor surface."
2. **Add install doc snippet** for `rootact.yaml` `mcp_servers` pointing at TeamShared
   when Option B is triggered — mirror Cursor `mcp.json` headers pattern.
3. **Clarify plugin positioning** — TeamShared is org brain; RACT/mex are repo-layer
   hygiene/execution; Cursor is IDE harness. Three layers, not three memory products.
4. **Do not build Option D** unless design partners ask — RACT and mex own repo/code
   hygiene; TeamShared wins on cross-repo recall, work queue, strategic memory.
5. **Watch receipt format** — if signed JSON run reports become a category standard,
   consider episodic `kind=event` ingest hook for RACT `report.json` (light Option C).
6. **Note license friction** — PolyForm NC limits commercial eval; flag in partner
   conversations before recommending RACT alongside TeamShared for business use.

---

## Files touched

- `product/sources/ract-research.md` — new research source
- `product/knowledge/ract-competitor-analysis.md` — this document

Answer your question from the findings. Fill the gaps before you commit to positioning.

---

## Next mogkit steps

1. Re-run `graphify` to ingest `ract-research.md` into `product/graph/graph.json`.
2. `discovery-query`: "Do terminal-first teams want org memory inside the harness MCP config?"
3. `interview-guide` — validate RACT vs Cursor vs TeamShared split for polyglot harness teams.
4. Hands-on: configure `rootact.yaml` with TeamShared MCP; capture one `--loop` run receipt.
5. `assumption-audit` — check if "Cursor is the only harness" assumption needs weakening.
