# Cognee competitor analysis (mogkit)

Generated via mogkit workflow: source capture → `discovery-query` (×3) →
`tradeoff-frame`. Source: `product/sources/cognee-research.md` (public docs at
[docs.cognee.ai](https://docs.cognee.ai/), GitHub README, MCP README, API index).
Corpus health: **thin** (single-source vendor/marketing research — no user
interviews, no hands-on `cognee.remember` / MCP install run in this corpus).

---

## Executive summary

**Cognee is a Tier-1 direct competitor to TeamShared** — not an adjacent layer
like mex or Headroom. It is a full agent-memory *platform*: triple-store
architecture (relational + vector + graph), v1.0 lifecycle ops (`remember`,
`recall`, `improve`, `forget`), MCP with Cursor/Codex/OpenClaw integrations,
multi-user dataset isolation, skills ingestion, induced ontologies, session→graph
bridging, and a managed **Cognee Cloud** SKU. At ~27.5k GitHub stars it matches
or exceeds GBrain's distribution footprint.

The overlap with TeamShared is substantial: both target persistent agent memory
via MCP, both move session context into durable stores, both support team-scoped
data and skills. They diverge on **product shape** — Cognee is graph-first
knowledge infrastructure with auto-routed retrieval; TeamShared is multi-pillar
org brain (semantic/episodic/procedural/skill/strategic/work) with human
governance (approvals, work queue, OTP console) and server-side capture.

For TeamShared planning: Cognee competes for the same "install an MCP memory
server" slot in Cursor. The interesting question is not whether Cognee exists in
the category — it clearly does — but whether TeamShared wins on **managed org
governance + team workflows** vs Cognee's **graph ontology depth + cloud GTM**.
Do not classify Cognee as Tier 3.

---

## discovery-query #1: What problem does Cognee solve?

### Findings

**1. Stateless LLM calls need a durable memory layer**
- *Confidence: Multi-source (docs intro + README)*
- "When you call an LLM, each request is stateless… You need a memory layer" — `cognee-research.md` / docs introduction
- Cognee turns documents into linked concepts + relationships, not just chunks
- TeamShared solves the same framing via MCP recall across pillars — same job-to-be-done.

**2. Agents need cross-session persistence with fast session cache**
- *Confidence: Single-source (docs)*
- `remember(session_id=...)` → session cache; `self_improvement=True` bridges to permanent graph via `improve` in background — main-operations docs
- TeamShared: Redis working memory + distiller queue → durable semantic/episodic — different mechanism, same session→long-term arc.

**3. Retrieval must combine semantic and structural search**
- *Confidence: Single-source (architecture docs)*
- Vector store for similarity; graph store for entity/relationship navigation; hybrid recall — architecture.md
- `recall()` auto-routes query type (summary, temporal, graph context, coding-rules, lexical) — recall.md
- TeamShared: hybrid recall across pillars + optional Neo4j graph; no query-type auto-router documented.

**4. Company brain / unify domain knowledge**
- *Confidence: Single-source (README marketing)*
- "Easily Build Company Brain - unify data from various sources" — GitHub README
- Multi-user mode with dataset permissions, tenants, roles — multi-user-mode.md
- TeamShared: multi-tenant org from day one with RLS + console — converging narrative, different implementation maturity signals.

**5. Breadth of ingest formats**
- *Confidence: Single-source (remember docs)*
- txt/md/pdf/images/audio/office docs/URLs/S3; optional docling/scraping extras — remember.md
- TeamShared ingest is primarily agent `memory_remember`, session distillation, and capture middleware — not document-pipeline-first.

### Gaps

- No user evidence that teams pick Cognee *because of* induced ontologies vs simpler vector recall.
- Unknown latency/cost of full `remember` pipeline vs TeamShared `memory_remember` on equivalent text.
- No hands-on validation of Cognee MCP boot alongside TeamShared plugin in Cursor.
- Marketing "5M+ SDK runs/month" unverified against TeamShared usage.

### Discovery questions

1. When you adopted agent memory, did you need document ingestion pipelines or conversational capture first?
2. Walk through your last memory miss — would graph traversal have helped, or was it a permissions/scoping issue?
3. Do you run memory self-hosted, managed cloud, or both — and who operates it?

---

## discovery-query #2: Where does TeamShared win vs Cognee?

### Findings

**1. TeamShared ships human team operations Cognee does not market**
- *Confidence: Single-source (internal + cognee-research gaps)*
- TeamShared: `work_*` queue, `memory_strategic_*` OKRs, `/app/approvals`, OTP console — AGENTS.md, shipped code
- Cognee API has datasets/permissions/skills but no work-status or strategic-plan tools in public API index
- Buyers needing "brain + task queue + OKRs" may prefer TeamShared console.

**2. Server-side capture is TeamShared-native; Cognee is remember-driven**
- *Confidence: Single-source (internal vs cognee-research)*
- TeamShared: `ToolCallCaptureMiddleware` + `POST /sessions/turns` across harnesses — AGENTS.md
- Cognee: agents call `remember` / session traces ingested via `improve` — no equivalent server-side transcript middleware documented
- Trust model divergence: automatic capture vs explicit/agent-initiated ingest.

**3. TeamShared's shared-brain read model is explicit**
- *Confidence: Single-source (internal)*
- `memory_recall` defaults to cross-agent durable visibility; `agent=` is opt-in filter — AGENTS.md hard rules
- Cognee: isolated recall per user's dataset permissions — secure by default, but different semantic ("my datasets" vs "our org brain").

**4. Cognee leads on graph infrastructure and retrieval routing**
- *Confidence: Single-source (cognee docs)*
- Triple-store with induced ontologies, schema inference, dataset graph visualization, truth subspace, global context index — cognee-research.md
- TeamShared graph is optional Neo4j + `memory_graph_relate`; curator writes wiki but graph is not the primary retrieval path.

**5. Cognee leads on distribution and deployment options**
- *Confidence: Multi-source (GitHub + docs)*
- ~27.5k stars, Apache-2.0, Docker MCP, Cloud SaaS, TypeScript/Rust SDKs, OpenClaw plugin, research paper — cognee-research.md
- TeamShared: teamshared.com managed + Cursor plugin; smaller public footprint.

**6. Cognee leads on skills-as-ingested-procedures with improvement proposals**
- *Confidence: Single-source (API index)*
- `ingest-skill`, list/get skills, skill-improvement proposals — API docs
- TeamShared: `memory_skill_set` / playbooks in Postgres — similar intent; Cognee ties skills to dataset graph context.

### Gaps

- No recall benchmark (TeamShared vs Cognee) on identical corpus.
- No interview: "we chose Cognee Cloud over TeamShared because…"
- Cognee Cloud pricing unknown — WTP comparison impossible.
- Unclear whether Cognee's `improve` distillation quality matches TeamShared distiller + curator output.

### Discovery questions

1. Does your team browse memory in a human UI, or only through the agent?
2. Would you pay for managed memory if ingest is agent-driven vs auto-captured?
3. Do you need work assignments and OKRs in the same system as agent memory?

---

## discovery-query #3: How does Cognee compare to GBrain in the competitive map?

### Findings

**1. Cognee and GBrain are the two large OSS "memory platform" peers**
- *Confidence: Multi-source (gbrain + cognee research)*
- GBrain ~23k stars; Cognee ~27.5k stars (Jul 2026) — public GitHub
- Both: MCP, company-brain narrative, session persistence, skills — cognee-research.md, gbrain-competitor-research.md

**2. GBrain differentiates on synthesis + gap analysis; Cognee on graph ontology pipeline**
- *Confidence: Single-source (each product's docs)*
- GBrain: `gbrain think` with explicit "what the brain doesn't know" — gbrain research
- Cognee: `recall` auto-routing + graph completion; no documented gap-analysis UX equivalent
- TeamShared: `memory_recall` returns records; `memory_think` adds synthesis — sits between the two.

**3. GBrain's brain-repo-as-git-SOTR vs Cognee's triple-store**
- *Confidence: Single-source*
- GBrain: markdown git repo synced to Postgres — gbrain research
- Cognee: relational + vector + graph with dataset handlers — architecture docs
- TeamShared: Postgres/Redis pillars, not git-SOTR — third storage philosophy.

**4. Cognee has managed cloud SKU; GBrain is self-host-first**
- *Confidence: Single-source (cognee cloud docs)*
- Cognee Cloud at platform.cognee.ai with collaboration — cognee-research.md
- GBrain: self-hosted Postgres/PGLite emphasis — gbrain research
- TeamShared teamshared.com is closer to Cognee Cloud GTM than GBrain OSS.

### Gaps

- No evidence on whether buyers evaluate Cognee vs GBrain as substitutes or complements.
- TeamShared may face a **two-front** competition: GBrain for synthesis UX, Cognee for graph+cloud infra.
- Unknown whether OpenClaw/Hermes ecosystems default to GBrain, Cognee, or both.

### Discovery questions

1. If you've tried GBrain, did you also evaluate Cognee — what tipped the choice?
2. Is managed cloud a requirement, or is self-host non-negotiable?
3. Do you need synthesized answers or structured graph exploration more?

---

## Head-to-head matrix

| Dimension | Cognee | TeamShared | GBrain | Edge |
|---|---|---|---|---|
| **Category** | Memory platform (graph+vector) | Multi-tenant org brain | Personal → company brain | Overlapping |
| **Stars (Jul 2026)** | ~27.5k | — | ~23k | Cognee/GBrain |
| **License** | Apache-2.0 | (teamshared) | MIT | Both OSS-friendly |
| **Core API** | remember/recall/improve/forget | memory_* / work_* / context_* | search/think + 30+ MCP | Different shapes |
| **Storage** | Relational + vector + graph | Postgres + Redis + pgvector pillars | Git markdown + Postgres | Cognee graph depth |
| **Session→durable** | Session cache + improve bridge | Working memory + distiller | Dream cycle | All three |
| **Query UX** | Auto-routed graph recall | Records + memory_think | Synthesis + gap analysis | GBrain synthesis |
| **Multi-user** | Dataset permissions, tenants, roles | RLS org_id, RBAC, OTP console | OAuth-scoped slices | TeamShared ops UI |
| **Managed SKU** | Cognee Cloud | teamshared.com | None marketed | Cognee/TeamShared |
| **Work queue** | Not in API | work_* + /app/work | Minions (internal) | TeamShared |
| **Strategic OKRs** | Not in API | memory_strategic_* | Schema packs | TeamShared |
| **Approvals** | Not surfaced | Agent write approvals | Admin scope gates | TeamShared |
| **Capture** | Agent remember / traces | Server middleware + sessions | Hooks + aggressive ingest | Different trust |
| **Skills** | Ingest SKILL.md to dataset | memory_skill_set + playbooks | 43 skillpack skills | Converging |
| **Ontology** | Induced + upload + infer schema | memory_ontology_* (early) | Schema packs | Cognee depth |
| **Integrations** | OpenClaw, Cursor, Codex, Claude | Cursor plugin + install.sh | OpenClaw/Hermes native | GBrain/Cognee reach |
| **Human UI** | Cloud UI + local UI | /app console wiki/work | Agent-query optimized | TeamShared work |
| **Eval rigor** | Research paper | Unit/integration tests | LongMemEval CI | GBrain |

---

## tradeoff-frame: How should TeamShared position against Cognee?

### The decision

Should TeamShared compete head-on with Cognee as a graph-memory platform, differentiate
as managed org-governance brain, or pursue integration/compatibility?

**Options:**
- **A.** Match Cognee graph depth (ontology induction, auto-routed recall, triple-store parity)
- **B.** Double down on org governance + work/strategic/approvals + human console (avoid graph arms race)
- **C.** Complementary positioning — "Cognee for document graphs, TeamShared for team ops + capture"
- **D.** Compete on managed SaaS — TeamShared as simpler teamshared.com vs Cognee Cloud
- **E.** Ignore Cognee; focus on GBrain as primary named competitor

### Real axes

1. **Engineering surface** — Cognee's graph pipeline + 14 MCP tools + cloud ops is a large platform bet.
2. **Buyer persona** — ML/platform engineer self-hosting Cognee vs eng lead wanting team queue + console.
3. **Ingestion model** — document pipeline + agent remember (Cognee) vs capture + session distillation (TeamShared).
4. **Retrieval philosophy** — graph auto-router (Cognee) vs pillar recall + optional synthesis (TeamShared).
5. **GTM** — viral OSS + cloud upsell (Cognee) vs managed team brain from install (TeamShared).

### Option profiles

**A — Graph parity**
- Optimizes: credibility in "knowledge graph memory" demos; answers "why not Cognee?"
- Sacrifices: quarters of graph/ontology engineering; distracts from work/strategic moat.

**B — Governance differentiation**
- Optimizes: teams needing work queue, OKRs, approvals, human wiki — features Cognee API doesn't surface.
- Sacrifices: loses graph-infrastructure narrative; may look "simpler" than Cognee in OSS comparisons.

**C — Complementary**
- Optimizes: clear Cursor boot story (Cognee for repo/docs graph, TeamShared for team recall/capture).
- Sacrifices: two MCP servers; user confusion; risk TeamShared becomes optional add-on.

**D — Managed SaaS race**
- Optimizes: buyers wanting zero-ops memory without self-hosting Cognee.
- Sacrifices: Cognee Cloud already has graph UI, collaboration, sync; feature parity pressure.

**E — Ignore**
- Optimizes: engineering focus; GBrain already mapped.
- Sacrifices: underestimates ~27k-star competitor in same MCP slot; duplicate "company brain" story.

### Reversibility

- **A** is largely one-way (graph infra is a long bet).
- **B** is two-way (governance ships incrementally).
- **C** is two-way (positioning/docs only) but hard to unwind if users pick one winner.
- **D** is two-way but commits GTM resources.
- **E** is reversible but increasingly costly as Cognee Cloud matures.

### Decisive evidence

- 5 design-partner interviews where teams **evaluated Cognee** (self-host or Cloud) and explain rejection criteria.
- Recall quality benchmark on shared corpus: TeamShared `memory_recall`/`memory_think` vs Cognee `recall`.
- Metric: do users with TeamShared also run Cognee MCP? (dual-install prevalence)
- Buyer saying "we need work queue + brain together" (validates B) vs "we need induced ontology" (validates A).

**Unspoken axis:** Cognee's star count and Berkeley/cloud GTM may make it the default
"serious" open-source memory pick in 2026 — TeamShared may be fighting distribution
and category definition simultaneously with both GBrain and Cognee.

Frame the decision. Then make the call yourself, or escalate to whoever owns it.

---

## Comparison matrix (Cognee vs TeamShared vs GBrain vs mex)

| Dimension | Cognee | TeamShared | GBrain | mex |
|---|---|---|---|---|
| **Tier** | 1 — direct | 1 — direct | 1 — direct | 3 — adjacent |
| **Primary scope** | Datasets / tenants | Multi-tenant org | Personal → company | Single repo |
| **Memory shape** | Graph + vector + relational | Five pillars + wiki | Git pages + Postgres | Git markdown scaffold |
| **MCP tools** | 14 (remember/recall/forget +) | ~70 memory/work/context | 30+ | 5 (draft PR) |
| **Cloud product** | Cognee Cloud | teamshared.com | None | None |
| **Synthesis** | Graph completion | memory_think | think + gaps | N/A |
| **Human ops** | Cloud UI | Console work/wiki | Minimal | CLI/TUI |
| **Moat** | Graph ontology + cloud | Org governance + capture | Synthesis + YC distro | Drift detection |

---

## Recommended product responses (not mogkit output — engineering judgment)

1. **Reclassify competitive map** — add Cognee as **Tier-1 peer alongside GBrain** in
   `product/README.md` and future graphify runs; tag `competitor`, `graph-memory`,
   `mcp-platform`.
2. **Do not conflate with mex/Headroom** — Cognee competes for the MCP memory slot,
   not the repo-scaffold or compression layer.
3. **Sharpen governance positioning** — work queue, strategic memory, approvals, OTP
   console are the honest differentiation vs Cognee's dataset/tenant model.
4. **Benchmark recall** — even a small shared-corpus eval vs Cognee `recall` closes
   the credibility gap Cognee's research paper and star count create.
5. **Document dual-MCP guidance** — if users install both, plugin rule should state
   division of labor (team recall/capture vs document graph): learn from mex analysis.
6. **Watch Cognee Cloud + OpenClaw plugin** — same harness surface as TeamShared;
   install.sh parity matters.
7. **Invest in `memory_think` gap analysis** — Cognee lacks GBrain-style gaps; TeamShared
   can win synthesis UX without matching full graph ontology (Option B lean).

---

## Files touched

- `product/sources/cognee-research.md` — new research source
- `product/knowledge/cognee-competitor-analysis.md` — this document

Answer your question from the findings. Fill the gaps before you commit to positioning.

---

## Next mogkit steps

1. Re-run `graphify` to ingest `cognee-research.md` into `product/graph/graph.json`.
2. `discovery-query`: "Do buyers choose graph memory platforms for ingest breadth or team governance?"
3. `interview-guide` — validate Cognee vs TeamShared split for teams evaluating MCP memory.
4. Hands-on: install `cognee-mcp` + run `remember`/`recall` on teamshared docs; capture latency/quality as user evidence.
5. `tradeoff-frame` refresh on combined GBrain+Cognee two-front competition.
