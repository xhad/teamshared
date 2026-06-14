# narrative-review — `prod-plan.md`

Review target: `prod-plan.md` (production-readiness roadmap prompt + staged
security hardening appendix). Read as a skeptical exec would on first pass.

---

## Central claim

TeamShared should evolve from PoC to a production multi-tenant SaaS because
organizations need durable **shared agent context infrastructure** — and the
technical roadmap in this doc is the right sequence to get there.

---

## Argument chain

| # | Link | Class | Note |
|---|---|---|---|
| 1 | Organizations need shared memory across users, agents, projects, and tools | **Asserted** | Stated as product vision; no user quote, interview, or usage data in the doc |
| 2 | "Production ready" is definable and achievable via the checklist in this memo | **Hand-waved** | Lists 20 deliverables and 4 phases but never defines a measurable "production ready" threshold — it's a feature inventory, not a success criterion |
| 3 | Multi-tenant isolation via `org_id` + RLS is the correct default for early-stage SaaS | **Supported** | Partially — the staged hardening appendix (Stages 0–3 **Done**) shows real execution on tenant/auth path; the doc's three-option comparison is requested of the reader, not resolved in the doc itself |
| 4 | Scoped retrieval must filter tenant + permission *before* vector search | **Supported** | Principle appears in both `plan.md` and current codebase conventions; security metrics (`auth_rejected`, etc.) suggest this is treated seriously |
| 5 | A four-phase roadmap (Foundation → Team Memory → Enterprise → Agent Network) de-risks delivery | **Hand-waved** | Phases are feature bundles with aspirational goals ("sell to serious org customers") but no entry/exit criteria per phase |
| 6 | Connectors (Slack, GitHub, Notion, …) in Phase 2 drive product usefulness | **Asserted** | Connector list is long (11 systems); no evidence any target customer asked for these or that connector-led adoption is the lever |
| 7 | Enterprise features (SSO, SCIM, SOC 2, data residency) in Phase 3 unlock revenue | **Asserted** | Standard enterprise playbook; no named design partner or lost-deal post-mortem cited |
| 8 | Phase 4 "Advanced Agent Memory Network" is the differentiation moat | **Missing → Asserted** | MCP-native interface, trust graph, conflict resolution — most of Phase 4 either exists today at PoC level (MCP, graph, distillation) or is unspecified; the doc doesn't explain why Phase 4 follows Phase 3 instead of being the core bet now |
| 9 | Memory poisoning / prompt injection requires explicit defenses | **Supported** | Dedicated section with concrete policy ("memory is context, not authority"); aligns with `IngestionPipeline` and approval queue in the codebase |
| 10 | The staged security roadmap (Stages 0–3) proves production trajectory | **Supported** | Status table shows substantial completion; this is the strongest evidential link in the entire doc — it demonstrates execution, not just intent |
| 11 | Prompt injection, connectors, observability, DR, etc. can ship incrementally without blocking Phase 1 | **Hand-waved** | Each subsystem gets a section but interdependencies (e.g., connector permission mirroring depends on RBAC model depends on team/project model) are not sequenced beyond the phase list |

---

## Claims presented as facts

| Phrase / claim | Why a skeptic contests it |
|---|---|
| *"Think of TeamShared as infrastructure for 'shared agent context' across an organization"* | Category creation — assumes orgs want a new infra layer rather than memory embedded in each agent tool (Cursor, Codex, Cloudflare Agent Memory) |
| *"Useful org memory product"* (Phase 2 goal) | "Useful" is undefined; no metric, no design partner, no before/after |
| *"Sell to serious org customers"* (Phase 3 goal) | Implies PMF exists before enterprise; doc builds enterprise before proving Phase 2 usefulness |
| *"Differentiated agentic memory infrastructure"* (Phase 4 goal) | Differentiated from what? Competitive section compares vector DBs and frameworks, not buyer alternatives |
| *Compare Postgres+pgvector vs Pinecone vs Weaviate… recommend best starting point* | Reasonable engineering ask, but the doc treats storage choice as settled risk while demand risk is unaddressed |
| *"Assume I want to start building immediately"* | Optimizes for engineering velocity; inverts the usual "validate demand, then build" sequence with no acknowledgment |

---

## The strongest counter

The memo is a **production engineering spec searching for a product**. It
assumes the hard problem is multi-tenant isolation, connector sync, and SOC 2 —
problems SaaS teams solve every day — while treating the actually hard and
unvalidated problem (do teams want a *shared* agent brain at all, and will they
trust it with cross-agent visibility by default?) as settled. A smart skeptic
would argue: Cursor already gives each developer agent memory; Cloudflare and
LangChain offer managed memory primitives; the incremental value of a team-wide
memory server doesn't clear the adoption friction of consent-first capture,
another MCP to configure, and a wiki humans may never open. The rational move is
to prove **cross-agent recall is valuable to 3–5 design partners** *before*
building Phase 3 enterprise or Phase 2's eleven connectors — not after. The
staged security work (Stages 0–3 Done) is real engineering progress, but it
hardens a thesis that hasn't been tested.

The doc does not engage this counter. Phase 1 is "safe multi-tenant MVP," not
"prove the shared-brain hypothesis with one org."

---

## What a skeptic attacks first

**Link #1 — that organizations need shared agent memory** — because every
subsequent phase, entity model, connector, and enterprise control assumes it, and
the doc provides zero demand evidence. A sharp reader sees 1,000 lines of
*how to build* and one sentence of *why anyone would use it*, then skips straight
to the security status table to see what's actually shipped. That's the tell:
execution credibility on infra, narrative gap on product.

Rewrite the narrative yourself. Use this to know where it bleeds.
