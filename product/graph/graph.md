# TeamShared — discovery graph

> **CORPUS HEALTH: THIN.** All five sources are internal product intent (plans,
> design memos, architecture docs). There is **zero user-research evidence** —
> no interviews, tickets, or support threads. Downstream mogkit skills will be
> gap-heavy *by design*. That is the correct, honest signal: TeamShared has a
> detailed plan and no captured user evidence behind it.

Generated 2026-06-05. Sources: 5. Inferred types: prd, memo, research, doc.
Nodes: 32 · Edges: 18 · Assumptions surfaced: 8.

## Segments (3)

| Segment | Distinct sources |
|---|---|
| Multi-tenant organizations / teams | 1 |
| Enterprise buyers | 1 |
| Agents / agentic workflows (first-class identities) | 1 |

## Needs (3)

| Need | Sources |
|---|---|
| Share memory across users, agents, projects, and tools | 1 |
| Persistent recall without overwhelming the context window | 1 |
| No cross-tenant memory leakage | 1 |

## Pains (1)

| Pain | Sources |
|---|---|
| Context rot from stuffing full history into the window | 1 |

## Features (9)

| Feature | Sources |
|---|---|
| Multi-tenant org architecture | 2 |
| Org/team/project/user/agent memory scopes | 1 |
| Role-based access control + per-read permission checks | 1 |
| Audit logs for all memory and permission events | 1 |
| Connectors (Slack, GitHub, Notion, Google Drive, Linear, MCP) | 1 |
| Consent-first, client-sanitized capture | 1 |
| Human console + continuously-updating memory wiki | 1 |
| LLM distillation + curator synthesizing wiki pages | 1 |
| MCP-native agent memory interface | 1 |

## Competitors / landscape (5)

| Entity | Sources |
|---|---|
| Pinecone (vector DB) / pgvector category | 1 |
| Neo4j context/knowledge graphs | 1 |
| LangChain / LlamaIndex memory modules | 1 |
| Cloudflare Agent Memory (managed memory primitives) | 1 |
| Hindsight-style distillation sub-agents | 1 |

> Note: these came from a single landscape paragraph in `plan.md`. They are the
> *category* TeamShared competes in, not a researched competitive analysis.

## Insights (2)

| Insight | Sources |
|---|---|
| Agent memory splits into four pillars (working/semantic/episodic/procedural) | 1 |
| Just-in-time retrieval beats keeping full history in-context | 1 |

## Outcomes (1)

| Outcome | Sources |
|---|---|
| Evolve TeamShared from PoC to production for multi-tenant org customers | 1 |

> No **measurable** outcome (activation, retention, paid conversion, recall
> quality) appears anywhere in the corpus. The only stated outcome is the
> engineering goal "get to production." Run `metrics-tree` to give the product a
> measurable target.

## Assumptions

Every load-bearing product bet that the corpus states without evidence. Each is
tied to the decision at risk if it's wrong.

- **Teams actually want cross-agent shared memory** — *The entire product thesis.
  If teams don't want a shared agent brain, every roadmap phase is built on sand.*
- **Orgs will pay for 'shared agent context' as infrastructure** — *Pricing/GTM
  viability; no willingness-to-pay evidence exists.*
- **Consent-first capture friction is what gates adoption** — *A whole phase.
  Declared a 'hard constraint', but no user/buyer is on record demanding it.*
- **Slack/GitHub/Notion/etc. connectors are the adoption lever** — *Connector
  roadmap sequencing; the list is asserted, not validated.*
- **SSO/SAML/SOC2 gate the deals worth chasing** — *Phase 3 enterprise
  investment may be sequenced too early.*
- **Default cross-agent visibility (shared brain) is what users want** — *Core
  read-path default; if users expect isolation, the open default is a trust risk.*
- **Humans will actually browse the memory wiki/console** — *The console +
  curator + wiki build; if nobody visits /app, it has no audience.*
- **LLM distillation yields durable, low-noise memory worth recalling** —
  *Recall quality, the core value; noisy memory collapses trust.*

## Next

- `assumption-audit` — triage these 8 assumptions by the decision at risk (done; see `knowledge/assumption-audit.md`).
- `discovery-query` — interrogate the graph for a specific question.
- `interview-guide` — turn the biggest gaps into a discovery interview.

The graph is a map of what your corpus says, not a model of the world. It grows when your sources do.
