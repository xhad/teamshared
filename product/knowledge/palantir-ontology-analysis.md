# Palantir Foundry ontology analysis (mogkit)

Generated via research synthesis: `palantir-foundry-ontology-research.md` +
TeamShared architecture (`AGENTS.md`, `prod-plan.md`, shipped graph/autolink/wiki).
Corpus health: **thin** (no user interviews on ontology UX).

---

## Executive summary

**Palantir Foundry's ontology is not a competitor to TeamShared** — it is an
enterprise **decision operating system** that unifies data, logic, and governed
actions on typed business objects. TeamShared is an **agent memory platform** with
pillars (semantic, episodic, skills, work, strategic) and optional graph edges.

The transferable insight is structural: Foundry treats **nouns (object types +
properties + links)** and **verbs (action types + audit)** as one API. TeamShared
today has strong nouns-in-text (memories, wiki, wikilinks, autolink) and scattered
verbs (70+ MCP tools) without a unifying ontological contract. Closing that gap —
lightly, without Foundry's weight — is a credible differentiation path alongside
GBrain synthesis and the five-pillar memory taxonomy.

**Headline recommendation:** add a thin **Org Ontology** layer: typed entity kinds,
constrained link types, governed action types, and per-entity Object Views in the
console. Keep memory-native ingestion; do not rebuild Foundry's dataset funnel.

---

## discovery-query: What does Foundry get right that TeamShared lacks?

### Findings

**1. Decision-centric framing beats storage-centric framing**
- *Confidence: Multi-source (Palantir docs + prod-plan alignment)*
- Foundry: "data + logic + actions" for operational decisions.
- TeamShared `prod-plan.md` Phase 4 already names "Organization knowledge graph"
  and "Memory trust graph" but ships today as optional Neo4j triples + vector recall.
- Gap: no explicit model of **which decisions** the brain supports (approve memory,
  assign work, link initiative to repo, etc.).

**2. Object types + properties > free-text subjects**
- *Confidence: Multi-source*
- Foundry: schema-defined object types with typed properties and shared properties.
- TeamShared: `memory_remember(subject=...)`, tags, `repo:`/`github:` tags — soft
  scoping, no org-wide entity schema.
- Consequence: `memory_graph_related("alice")` works but cannot answer "all
  `Person` objects linked to `Project` teamshared via `owns`" without convention.

**3. Link types are schema, not just predicates**
- *Confidence: Multi-source*
- Foundry: link types declared between object types; design rules against spiderwebs.
- TeamShared: `memory_graph_relate(subject, predicate, object)` — any string
  predicate; autolink infers `mentions`, `works_at`, `works_on` (GBrain-like).
- TeamShared autolink (`src/teamshared/memory/autolink.py`) is a strong foundation;
  missing piece is **org-scoped link type registry** with cardinality hints.

**4. Action types are the kinetic layer agents need**
- *Confidence: Multi-source*
- Foundry: parameterized, validated, audited mutations; write-back to external systems.
- TeamShared: direct MCP mutations (`memory_remember`, `work_update`,
  `memory_strategic_*`) — powerful but undifferentiated; strategic writes go to
  approval queue, most others do not.
- Opportunity: wrap high-risk mutations as named **actions** with precondition checks
  and unified audit log (console + episodic).

**5. Interfaces enable polymorphism across pillars**
- *Confidence: Single-source (Palantir docs)*
- Foundry: `Facility` implemented by `Airport`, `Hangar`, etc.; actions/search over
  interface.
- TeamShared pillars are separate stores (work, strategic, semantic, procedural).
- No shared shape for "things with status, owner, and approval gate" across work items,
  memory approvals, and strategic proposals.

**6. Object Views are the human UX for entity-centric brains**
- *Confidence: Multi-source (Palantir + TeamShared wiki plan)*
- Foundry: per-object hub — bio, links, metrics, apps.
- TeamShared: curator-written `wiki_pages` by subject slug; `/app/wiki/topic/{slug}`
  falls back to raw records. Work and strategic links to same subject are not unified.

**7. Foundry's weight is not the goal**
- *Confidence: Multi-source*
- OMS, Funnel, Object Storage V2, Workshop — quarters/years of infra.
- TeamShared buyers (YC company-brain segment) need **30-minute agent install**, not
  ontology manager GUI.
- Programmatic ontology (Foundry weakness) is TeamShared's natural fit — MCP-native
  schema proposals with human approval.

### Gaps

- No user evidence that teams want Foundry-style object typing vs GBrain-style prose.
- Unknown whether governed action types reduce agent errors in practice.
- No benchmark: does typed ontology improve recall vs autolink-only (GBrain +31.4 P@5)?
- Enterprise buyers may want Foundry itself, not ontology patterns in a memory SaaS.

### Discovery questions

1. When you look up "Project X" in team memory, do you want one hub page (wiki + tasks
   + people + timeline) or separate tools per pillar?
2. Should agents propose new entity types (`Customer`, `Deal`) or only use a fixed
   org schema?
3. Which mutations must be governed actions (audit + approval) vs free MCP writes?
4. Do you model relationships explicitly (`alice manages bob`) or rely on prose + search?

---

## Architecture mapping: Foundry → TeamShared

| Foundry | TeamShared today | Proposed evolution |
| --- | --- | --- |
| Object type | `subject`, wiki slug, tags | `ontology_object` kinds: Person, Project, Repo, Initiative, … |
| Property | memory metadata, work fields | Typed properties per kind (status, owner, dates) |
| Link type | `memory_graph_edges.predicate` | Registered link types + cardinality (`owns`, `blocked_by`) |
| Action type | MCP tool per mutation | `ontology_action_apply(name, params)` with validation + audit |
| Interface | — | `Approvable`, `Assignable`, `ScopedToRepo` across pillars |
| Function | skills / playbook steps | Keep skills; attach to action types as validators |
| Object View | wiki topic page | `/app/entity/{kind}/{id}` hub |
| OMS | — | `ontology_schema` table + `memory_ontology_*` MCP tools |
| Action log | audit logs (partial) | `ontology_action_log` + episodic events |
| Roles on types | org RBAC | RBAC + per-kind/link/action permissions |

### What to skip (Foundry baggage)

- Dataset-row object backing and Funnel-style ETL
- Object Storage V2 scale paths
- GUI-only Ontology Manager as primary interface
- Geospatial / industrial object libraries
- Write-back to SAP/ERP (until connector phase proves demand)

---

## tradeoff-frame: How much ontology should TeamShared adopt?

### The decision

Should TeamShared invest in a **Foundry-inspired org ontology** or stay a
**memory-first** product with lightweight graph edges?

**Options:**

- **A.** Full ontology layer (object types, link types, action types, interfaces)
- **B.** Graph++ only (typed link registry + stronger autolink, no object schema)
- **C.** Object Views only (UX hub per entity, no schema change)
- **D.** Status quo — vector + episodic + optional graph triples

### Real axes

1. **Agent ergonomics** — typed objects/actions vs fewer concepts (remember/recall).
2. **Engineering cost** — schema migration, console UI, MCP surface vs curator tweaks.
3. **Enterprise trust** — governed actions + audit vs speed of raw MCP tools.
4. **Category positioning** — "company brain" vs "ontology-lite for agents".
5. **GBrain parity** — graph autolink already table stakes; ontology goes further.

### Option profiles

**A — Full ontology layer**
- Optimizes: enterprise decision narrative, differentiation from both GBrain and raw RAG.
- Sacrifices: complexity, onboarding friction, months of schema/console work.

**B — Graph++**
- Optimizes: retrieval quality (constrained predicates, cardinality), reuses autolink.
- Sacrifices: polymorphism, governed actions, unified Object Views.

**C — Object Views only**
- Optimizes: human browse UX, demo polish, reuses wiki + work + episodes APIs.
- Sacrifices: agent-side structure; underlying fragmentation remains.

**D — Status quo**
- Optimizes: shipping speed, MCP simplicity.
- Sacrifices: Foundry/GBrain graph trajectory; enterprise "how do agents write safely?"

### Reversibility

- **A** is mostly one-way once customers depend on custom object types.
- **B** is two-way and can precede A (link registry without full object schema).
- **C** is two-way and valuable independent of schema.
- **D** is two-way but competitive window may close as GBrain graph matures.

### Decisive evidence

- Design partner asks for "one page per customer/project" (validates C or A).
- Agent failure logs show wrong-tool mutations (validates A action types).
- Recall benchmark shows typed links beat free predicates by >10% P@5 (validates B).
- Buyers say ontology sounds "too heavy" (validates B or D).

**Recommended sequencing:** **C → B → A** — ship Object Views first (weeks), then link
type registry + autolink alignment (weeks), then governed action types for
high-risk mutations (months). Interfaces last.

---

## Recommended product responses

Prioritized improvements for TeamShared, informed by Foundry but sized for a
company-brain product:

### P0 — Entity hub (Object View)

Unify existing pillars in console:

- `/app/entity/{slug}`: curated wiki article + semantic memories + episodic timeline
  slice + linked `work_*` items + graph neighbors + pending approvals mentioning entity.
- Agents: `memory_entity_view(name=...)` MCP tool returning the same bundle.

*Foundry inspiration:* Object Views. *TeamShared advantage:* no Funnel — assemble
from existing stores.

### P1 — Org link type registry

- Admin-defined or seed link types: `works_on`, `owns`, `blocked_by`, `mentions`,
  `parent_of`, `assigned_to`.
- Validate `memory_graph_relate` predicates against registry (warn or reject unknown).
- Extend autolink to emit registered types only; document cardinality in schema.

*Foundry inspiration:* Link types with anti-spiderweb discipline. *GBrain alignment:*
zero-LLM autolink on write already shipped in code — register and measure it.

### P2 — Governed action types (kinetic layer)

Wrap high-impact MCP mutations:

| Action | Wraps | Validation | Audit |
| --- | --- | --- | --- |
| `remember_fact` | `memory_remember` | PII scan, quarantine rules | action log |
| `propose_strategy` | `memory_strategic_*` | approval required | action log |
| `assign_work` | `work_update` | assignee exists in org | action log |
| `link_entities` | `memory_graph_relate` | predicate in registry | action log |

Expose `memory_action_apply(action_type, params)` as the agent-facing verb; keep
underlying tools for backward compatibility.

*Foundry inspiration:* Action types with audit. *TeamShared advantage:* approval
queue already exists — extend pattern.

### P3 — Core object types (nouns)

Seed org ontology kinds aligned to existing pillars:

- `Person` (account/email), `Agent`, `Project`, `Repository`, `Initiative`,
  `Memory`, `WorkItem`, `Skill`, `Playbook`.
- Map `memory_remember(subject=...)` → `Memory` object linked to subject entity.
- Distiller proposes new objects; human approves in console (like strategic writes).

*Foundry inspiration:* Object types. *Constraint:* emergent + approved, not
GUI-first ontology manager.

### P4 — Interfaces across pillars

- `Approvable` — strategic statements, agent-created tasks, quarantined memories.
- `Assignable` — work items, initiatives.
- `Scoped` — repo/github tagged entities.
- `Temporal` — episodic events, sessions.

Enables one console filter ("everything awaiting my approval") and one agent query
pattern.

### P5 — Decision-centric ontology design playbook

Add mogkit/teamshared skill: `ontology-design` — model decisions not datasets;
name objects in business language; cap link cardinality; every object type must
answer "what action does an agent take on this?"

---

## Comparison to GBrain (ontology angle)

| Dimension | GBrain | Foundry | TeamShared direction |
| --- | --- | --- | --- |
| Entity extraction | Zero-LLM on write | Schema-defined object types | Autolink + optional object types (P3) |
| Edge typing | `works_at`, `invested_in`, … | Link types in OMS | Link registry (P1) |
| Mutations | Page write API | Action types | Governed actions (P2) |
| Per-entity UX | Page + search | Object Views | Entity hub (P0) |
| Governance | OAuth scope | Ontology roles | RBAC + approvals + action log |

TeamShared can leapfrog GBrain on **governed multi-tenant actions** while matching
its graph autolink — Foundry provides the blueprint for the kinetic layer GBrain
does not emphasize.

---

## Files touched

- `product/sources/palantir-foundry-ontology-research.md` — new research source
- `product/knowledge/palantir-ontology-analysis.md` — this document

## Next mogkit steps

1. Re-run `graphify` to ingest the Palantir source into `product/graph/graph.json`.
2. Run `discovery-query`: "Which ontology primitives matter for 10–50 person teams?"
3. Run `tradeoff-frame` against GBrain analysis — ontology vs synthesis priority.
4. Add 2–3 design-partner interviews probing Object View and action-type demand.
