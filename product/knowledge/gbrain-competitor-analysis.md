# GBrain competitor analysis (mogkit)

Generated via mogkit workflow: `graphify` → `discovery-query` → `tradeoff-frame`.
Sources: `product/sources/gbrain-competitor-research.md`, `company-brain-yc-rfs.md`,
plus internal TeamShared intent docs. Corpus health: **thin** (no user interviews).

---

## Executive summary

**GBrain is the most credible direct competitor to TeamShared** in the YC "company
brain" category. It is not a vector DB or framework — it is a full agent-memory
product with synthesis, graph traversal, gap analysis, MCP tools, and a company-brain
multi-user mode. Garry Tan (YC CEO) ships it in production behind OpenClaw/Hermes;
Tom Blomfield's YC RFS names it as the reference implementation.

TeamShared and GBrain overlap on MCP agent memory, multi-user scoping, graph
relationships, skills/playbooks, and overnight enrichment workers. They diverge on
**answer shape** (records vs synthesized prose with gap analysis) and
**go-to-market** (managed multi-tenant SaaS vs self-hosted open-source with
agent-install protocol).

---

## discovery-query: Where does TeamShared win vs GBrain?

### Findings

**1. Multi-tenant org infrastructure is TeamShared's native shape**
- *Confidence: Single-source (internal)*
- "Multi-tenant organizations" / "`org_id` on every customer table" — `prod-plan.md`, `plan.md`
- GBrain's company brain is a newer tutorial layer ("10-50 person team, ~90 min");
  TeamShared has RLS, org-scoped API keys, OTP console, and approval queues shipped.

**2. Server-side ToolCallCaptureMiddleware is a TeamShared differentiator (capture not hook-dependent)**
- *Confidence: Single-source (internal + shipped code)*
- TeamShared: `ToolCallCaptureMiddleware` + `POST /sessions/turns` record every turn across harnesses (gated by `capture_enabled`) — `AGENTS.md`
- GBrain: capture depends on per-harness hooks (`INSTALL_FOR_AGENTS.md`).
- The graph previously carried an `feature-consent-capture` node; consent-first capture has since been removed from the product.

**3. TeamShared has pillars GBrain doesn't market: work queue, strategic OKRs, approvals**
- *Confidence: Single-source (internal + shipped code)*
- TeamShared: `work_*`, `memory_strategic_*`, RBAC and guarded active writes
- GBrain research doc notes no equivalent work-queue or approval-queue surface.

**4. GBrain leads on synthesis UX and retrieval rigor**
- *Confidence: Single-source (GBrain public docs)*
- "`gbrain think` … honest note on what the brain doesn't know yet. The gap analysis is the differentiator."
- Benchmarked retrieval (+31.4 P@5 over graph-disabled), eval CI gates (NamedThingBench, LongMemEval).
- TeamShared `memory_recall` returns ranked records; curator writes wiki pages but does not expose gap analysis on query.

**5. GBrain leads on distribution and category definition**
- *Confidence: Multi-source (gbrain research + YC RFS)*
- 23.4k GitHub stars; "We need Garry's G-Brain, but for every business in the world."
- Native OpenClaw/Hermes install path; `INSTALL_FOR_AGENTS.md` agent-operated setup.
- TeamShared: Cursor plugin + `install.sh`, smaller public footprint.

**6. Both target "company brain" — market is validated, winner unclear**
- *Confidence: Single-source (YC RFS)*
- "I think every company in the world is going to need one."
- Category is real; neither product has user-evidence in this corpus proving buyer preference.

### Gaps

- No interviews with teams choosing between managed memory vs self-hosted GBrain.
- No evidence on whether buyers want aggressive auto-capture (GBrain) or a more conservative default.
- No head-to-head recall quality benchmarks (TeamShared vs GBrain on same corpus).
- GBrain pricing model unknown; TeamShared willingness-to-pay unvalidated.
- Unknown whether enterprise buyers trust YC-CEO open-source vs vendor SaaS.

### Discovery questions

1. When your team evaluated agent memory, did you try self-hosting (GBrain-style) or want a managed org service? What broke?
2. Walk me through the last time an agent gave you wrong context — was the failure retrieval, synthesis, or permissions?
3. Would you accept an agent ingesting Slack/email automatically, or do you want a per-source capture gate?
4. Do humans on your team browse a memory wiki, or do only agents query memory?
5. What would make you pay for memory infrastructure vs run it on your own Postgres?

---

## Head-to-head matrix

| Dimension | GBrain | TeamShared | Edge |
|---|---|---|---|
| **Category** | Personal brain → company brain | Multi-tenant org brain from day one | Depends on buyer size |
| **Distribution** | 23k stars, YC CEO, OpenClaw native | Cursor plugin, teamshared.com | GBrain |
| **Agent interface** | MCP (30+ tools) + CLI | MCP (~70 tools) | TeamShared breadth |
| **Query UX** | `search` (chunks) + `think` (synthesis + gaps) | `memory_recall` (records) + curator wiki | GBrain synthesis |
| **Graph** | Auto-link on write, zero LLM, typed edges | Optional Neo4j, `memory_graph_*` | GBrain maturity |
| **Ingestion** | Aggressive (signal detector, webhooks, dream cycle) | Server-side middleware, `capture_enabled` flag | Different defaults |
| **Skills** | 43 markdown skills in skillpack | Skills pillar + procedural playbooks | Converging |
| **Multi-user** | OAuth-scoped slices, leak fuzz-tested | RLS, RBAC, org isolation, OTP console | TeamShared ops depth |
| **Work management** | Minions job queue (internal) | `work_*` MCP tools + `/app/work` | TeamShared |
| **Approvals** | Admin scope gates | Agent writes → approval queue | TeamShared |
| **Strategic memory** | Schema packs (page types) | `memory_strategic_*` OKRs | Different models |
| **Eval / quality** | LongMemEval, NamedThingBench, replay CI | Unit/integration tests, smoke scripts | GBrain rigor |
| **Storage** | Git markdown repo + Postgres sync | Mem0 + Redis + Postgres pillars | Different SOtR |
| **License** | MIT open-source | (teamshared — check license) | GBrain self-host appeal |

---

## tradeoff-frame: Positioning vs GBrain

### The decision

How should TeamShared position against GBrain — compete head-on as a "company brain,"
or differentiate as managed multi-tenant agent-memory infrastructure with governance?

**Options:**
- **A.** Match GBrain feature-for-feature (synthesis, graph autolink, dream cycle, schema packs)
- **B.** Double down on managed multi-tenant + work/strategic/approvals (governance layer)
- **C.** Integrate/compatibility path — TeamShared as the team brain layer GBrain lacks (hosted org mode)
- **D.** Ignore GBrain; pursue enterprise connectors and SSO as the wedge

### Real axes

1. **Time-to-moat** — GBrain has 23k stars and eval CI; catching up on retrieval/synthesis is quarters of work.
2. **Buyer persona** — power-user self-hoster (GBrain) vs team lead wanting managed infra (TeamShared).
3. **Ingestion trust model** — auto-capture breadth (GBrain) vs flag-gated server-side capture (TeamShared).
4. **Answer shape** — raw recall + wiki vs synthesized answers with explicit gaps.
5. **Revenue model** — open-source self-host vs hosted SaaS with org billing.

### Option profiles

**A — Feature parity**
- Optimizes: competitive credibility in demos, answers "why not GBrain?"
- Sacrifices: engineering bandwidth; may need to match GBrain's ingest breadth.

**B — Governance differentiation**
- Optimizes: enterprise trust, approval queues, work/strategic pillars, managed ops.
- Sacrifices: viral open-source adoption; may feel "slower" than GBrain's 30-min agent install.

**C — Compatibility / hosted GBrain-alternative**
- Optimizes: teams already on OpenClaw/Hermes who want org mode without self-hosting.
- Sacrifices: product clarity; risk of being "GBrain but hosted" without synthesis moat.

**D — Enterprise wedge**
- Optimizes: deals that need SSO/SOC2/connectors.
- Sacrifices: GBrain may add enterprise features; design partners may self-host first.

### Reversibility

- **A** is largely one-way (synthesis + eval infra is a long bet).
- **B** is two-way (governance features can ship incrementally).
- **C** is two-way but positions TeamShared as derivative unless synthesis catches up.
- **D** is two-way but slow; enterprise sales cycles don't validate product-market fit fast.

### Decisive evidence

- 5 design-partner interviews where teams **chose self-hosted GBrain** and explain why TeamShared wouldn't work.
- Recall/synthesis benchmark on identical corpus showing TeamShared within 10% of GBrain P@5.
- Buyer saying "we'd pay for hosted memory **only if** capture is flag-gated, not auto-on" (validates B).
- Buyer saying "we need `think`-style answers, not record lists" (validates A investment in synthesis).

**Unspoken axis:** GBrain's YC CEO author may make "build on GBrain" the default advice in the
category — TeamShared may be fighting distribution, not features.

---

## Recommended product responses (not mogkit output — engineering judgment)

These are implications, not mogkit recommendations:

1. **Add `memory_think` or extend `memory_assemble_context`** with gap analysis ("what we don't know / what's stale") — closes the biggest UX gap vs GBrain.
2. **Ship graph autolink on write** without LLM — GBrain proves this is high-ROI for retrieval.
3. **Document the managed multi-tenant governance wedge** explicitly in positioning — don't hide it; it's the trust story for teams who won't run Garry's aggressive self-hosted ingest.
4. **OpenClaw/Hermes compatibility** — ensure `install.sh` is as agent-friendly as `INSTALL_FOR_AGENTS.md`; same harnesses, different brain.
5. **Run retrieval benchmarks** — even a small NamedThingBench-style suite would close the eval credibility gap.

---

## Files touched

- `product/sources/gbrain-competitor-research.md` — new research source
- `product/graph/graph.json` — re-graphified with GBrain nodes/edges
- `product/graph/graph.md` — updated summary
- `product/knowledge/gbrain-competitor-analysis.md` — this document

Answer your question from the findings. Fill the gaps before you commit to positioning.
