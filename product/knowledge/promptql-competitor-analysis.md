# PromptQL competitor analysis (mogkit)

Generated via mogkit workflow: `graphify` → `discovery-query` → `tradeoff-frame`.
Sources: `product/sources/promptql-research.md` (public docs) plus internal
TeamShared intent docs. Corpus health: **thin** (single-source competitive
intelligence, no user interviews).

---

## Executive summary

**PromptQL is a Tier-2 adjacent competitor**, not a direct memory-substrate rival
like GBrain or Cognee. Hasura-backed and positioned as a **multiplayer AI for
teams that maintains a shared context wiki**, PromptQL's center of gravity is
live data + BI artifacts (tables, charts, dashboards) rather than agent memory.
It overlaps TeamShared on the phrase "shared context" and on the wiki surface,
but its buyer is likely a data-driven team that wants an AI analyst, not an
engineering team wiring memory across multiple agents.

The most credible threat is **category confusion**: if buyers evaluating
"shared brain" solutions shortlist PromptQL alongside TeamShared, PromptQL's
story (data-live connectors, per-user permissions, multiplayer thread) could
win deals that TeamShared wants. TeamShared's defensible differentiation remains
**multi-tenant agent memory infrastructure** (MCP tools, five pillars,
work/OKR/ontology governance, server-side capture) rather than BI or data
connectivity.

---

## discovery-query: Where does PromptQL overlap with TeamShared?

### Findings

**1. PromptQL and TeamShared both use "shared context" language, but mean different primary products**
- *Confidence: Single-source (PromptQL docs) + internal*
- PromptQL: "multiplayer AI for your team that maintains a shared context wiki."
- TeamShared: "shared agent memory MCP server for engineering teams" / "infrastructure for shared agent context across an organization."
- The overlap is marketing, not architecture.

**2. PromptQL's center of gravity is live data + BI artifacts, not agent memory**
- *Confidence: Single-source (PromptQL docs)*
- "Connect databases (Postgres, Snowflake, BigQuery, Databricks, and more) and SaaS integrations..."
- "Ask in plain language and get back artifacts — tables, charts, reports, and interactive dashboards."
- TeamShared has no comparable artifact generation or first-class data-connector sync (connectors are listed as not shipped in shipped-state).

**3. PromptQL enforces permissions at the data layer; TeamShared enforces them at the memory/org layer**
- *Confidence: Single-source (PromptQL docs) + internal*
- PromptQL: "per-user permissions enforced at the data layer."
- TeamShared: RLS, RBAC, org isolation, approval queue, audit logs.
- Different permission substrate: live query authorization vs durable memory authorization.

**4. PromptQL has a multiplayer collaboration surface TeamShared lacks**
- *Confidence: Single-source (PromptQL docs)*
- "Multiple people can join the same thread, @-mention each other and the agent, and collaborate in real time."
- TeamShared's human collaboration is async (work queue, wiki, comments) rather than a live chat thread.

**5. PromptQL delegates coding tasks to Claude Code/Codex; it is not a memory server for arbitrary agents**
- *Confidence: Single-source (PromptQL docs)*
- "Connect coding agents like Claude Code or Codex running on your own machines. PromptQL can delegate code investigation, feature development, and browser testing tasks securely."
- TeamShared exposes ~70 MCP tools for any harness; PromptQL appears to be the product, not a substrate.

**6. PromptQL ships a secure cloud coding environment; TeamShared does not**
- *Confidence: Single-source (PromptQL docs)*
- "secure coding environment in the cloud for the AI to write and run code in to solve problems."
- TeamShared has no cloud execution sandbox.

**7. PromptQL has no published memory taxonomy, work queue, or agent-write governance**
- *Confidence: Single-source (PromptQL docs) + internal gap analysis*
- PromptQL docs do not describe a `MemoryKind`-style taxonomy, `work_*` tools, strategic OKRs, or an approval queue for agent writes.
- TeamShared's five-pillar model and governance layers are distinct.

### Gaps

- No interviews with teams that chose PromptQL for shared context / wiki.
- No pricing or packaging surfaced in the docs.
- No evidence whether PromptQL exposes memory to external agents via MCP or only hosts its own agent.
- No benchmark or eval claims for recall/synthesis quality.
- Unknown whether PromptQL's "shared wiki" is durable semantic memory or ephemeral chat context.
- No clarity on whether PromptQL's cloud sandbox competes with TeamShared's capture/ingestion story or is orthogonal.

### Discovery questions

1. When you looked for a "shared brain" for your agents, did PromptQL come up? Did you evaluate it as a memory product or as a data analyst?
2. What matters more: live queryable data connectors (PromptQL) or durable cross-agent memory (TeamShared)?
3. Do you want a multiplayer chat thread with an AI, or async work queues + wiki pages?
4. Would you pay for memory infrastructure separately from a BI/agent product, or do you expect them bundled?
5. How important is it that memory be accessible to any MCP-speaking agent vs. only the product's built-in agent?

---

## Head-to-head matrix

| Dimension | PromptQL | TeamShared | Edge |
|---|---|---|---|
| **Primary category** | Multiplayer AI analyst + shared wiki | Multi-tenant agent memory server | Different buyers, some overlap |
| **Distribution** | Web, desktop, mobile, Slack | MCP + Cursor plugin + web console | PromptQL surface breadth |
| **Agent interface** | Built-in agent + delegates to Claude Code/Codex | MCP-native (~70 tools) for any harness | TeamShared openness |
| **Data connectors** | First-class: Postgres, Snowflake, BigQuery, SaaS | Not shipped as first-class sync | PromptQL |
| **Permissions** | Per-user at data layer | RLS + RBAC + org isolation | Different but both credible |
| **Query UX** | Plain language → artifacts (charts, dashboards) | `memory_recall` records + `memory_think` synthesis | Different answer shapes |
| **Collaboration** | Real-time multiplayer thread | Async work queue + wiki + comments | PromptQL live, TeamShared structured |
| **Memory taxonomy** | Implied wiki | Five-pillar `MemoryKind` + graph | TeamShared explicit |
| **Governance** | Not surfaced | Approval queue, RBAC, audit | TeamShared |
| **Cloud execution** | Secure sandbox for agent code | None | PromptQL |
| **Capture** | Connector/chat ingestion | Server-side `ToolCallCaptureMiddleware` | Different models |
| **Pricing** | Not surfaced | Not surfaced | Unknown |

---

## tradeoff-frame: How should TeamShared position against PromptQL?

### The decision

Should TeamShared treat PromptQL as a competitor to respond to, an adjacent
product to ignore, a potential integration partner, or a category framing threat?

**Options:**
- **A.** Ignore PromptQL — different buyer (data analyst) and different product shape.
- **B.** Counter-position as the agent-memory substrate underneath products like PromptQL.
- **C.** Add live data/BI artifact capabilities to match PromptQL's headline value.
- **D.** Partner / integrate — let PromptQL's agent read/write TeamShared memory for durable cross-agent context.

### Real axes

1. **Buyer identity** — data analyst teams vs. engineering agent teams.
2. **Product layer** — AI analyst over live data vs. memory substrate for arbitrary agents.
3. **Go-to-market clarity** — adding BI/data connectors changes TeamShared's story.
4. **Engineering cost** — matching PromptQL is large (connectors, artifacts, real-time multiplayer, sandbox).
5. **Category confusion** — if buyers conflate "shared wiki" with "shared agent memory", PromptQL becomes a real alternative.

### Option profiles

**A — Ignore PromptQL**
- Optimizes: focus on direct memory competitors (GBrain, Cognee, Hivemind); avoids scope creep.
- Sacrifices: leaves any category-confusion deals on the table; assumes buyers can tell the difference.

**B — Counter-position as the memory layer underneath**
- Optimizes: reframes TeamShared as infrastructure that products like PromptQL could use for durable agent memory.
- Sacrifices: requires sales/partnership motion; PromptQL may build its own memory store.

**C — Match live data + BI artifact capabilities**
- Optimizes: competes directly with PromptQL's value prop; may broaden TAM.
- Sacrifices: huge engineering cost; dilutes the memory-server focus; connectors are explicitly not shipped today.

**D — Partner / integrate**
- Optimizes: turns a potential framing competitor into a channel; PromptQL users get durable memory, TeamShared gets exposure.
- Sacrifices: requires PromptQL's willingness; may cede the "AI analyst" UI layer.

### Reversibility

- **A** is two-way (can always respond later if PromptQL enters the memory space).
- **B** is two-way but slow (partnership positioning takes time).
- **C** is largely one-way (building data/BI infra commits the product to a broader shape).
- **D** is two-way (integration can be retired if it doesn't produce deals).

### Decisive evidence

- A buyer saying "we compared PromptQL and TeamShared for the same use case" — establishes real competition.
- A buyer saying "we need memory that works across Claude Code, Cursor, and Codex, not just one product's agent" — validates B/D.
- A buyer saying "we picked PromptQL because it had live data connectors" — validates C if repeated often.
- A buyer saying "we see PromptQL as BI and TeamShared as memory" — validates A.

**Unspoken axis:** PromptQL is backed by Hasura, which already owns data-access authorization. If Hasura decides to add MCP memory tools, PromptQL could become a direct competitor faster than a standalone startup.

---

## Recommended product responses (not mogkit output — engineering judgment)

These are implications, not mogkit recommendations:

1. **Monitor, don't match.** PromptQL is adjacent today. The biggest risk is category confusion, not feature parity. Keep the positioning sharp: "memory infrastructure for agents," not "AI analyst over data."
2. **Document the boundary.** In the landing page and README, explicitly contrast first-class data connectors (not shipped) with memory capture/ingestion. This preempts the "why not PromptQL?" question.
3. **Explore partnership/integration.** If PromptQL's agent can speak MCP, a `teamshared` memory backend could give PromptQL durable cross-agent memory — turning a competitor into a customer/channel.
4. **Don't build a BI artifact layer unless design partners demand it.** Live data connectors and artifact generation are a different product; adding them risks the memory focus.
5. **Keep an eye on Hasura's moves.** Hasura's data-layer permissions + PromptQL's agent could evolve into a memory product if they add MCP exposure or durable recall primitives.

---

## Files touched

- `product/sources/promptql-research.md` — new research source
- `product/graph/graph.json` — re-graphified with PromptQL nodes/edges
- `product/graph/graph.md` — updated summary
- `product/knowledge/promptql-competitor-analysis.md` — this document
- `product/README.md` — competitor table updated

Answer your question from the findings. Fill the gaps before you commit to positioning.
