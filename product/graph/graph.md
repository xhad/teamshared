# TeamShared — discovery graph

> **CORPUS HEALTH: THIN.** Seven sources: five internal product-intent docs plus two
> external research artifacts (YC RFS, GBrain competitor research). There is still
> **zero user-research evidence** — no interviews, tickets, or support threads.
> GBrain research is single-source public marketing/docs, not buyer validation.

Generated 2026-06-19. Sources: 7. Types: research, prd, memo, doc.
Nodes: 48 · Edges: 32 · Assumptions surfaced: 10.

## Segments (5)

| Segment | Distinct sources |
|---|---|
| Multi-tenant organizations / teams | 1 |
| Enterprise buyers | 1 |
| Agents / agentic workflows | 1 |
| Founders building "company brain" (YC RFS) | 1 |
| Power users running OpenClaw/Hermes agents | 1 |

## Needs (6)

| Need | Sources |
|---|---|
| Share memory across users, agents, projects, tools | 1 |
| Persistent recall without overwhelming context window | 1 |
| No cross-tenant memory leakage | 1 |
| Synthesized answers with citations (not raw page lists) | 1 |
| Know what the brain doesn't know yet (gap analysis) | 1 |
| Turn institutional knowledge into executable AI skills | 1 |

## Pains (3)

| Pain | Sources |
|---|---|
| Context rot from stuffing full history into window | 1 |
| Coding agents amnesiac about non-code knowledge | 1 |
| Company know-how scattered across heads, email, Slack | 1 |

## Features (16)

| Feature | Sources |
|---|---|
| Multi-tenant org architecture | 2 |
| Org/team/project/user/agent memory scopes | 1 |
| RBAC + per-read permission checks | 1 |
| Audit logs | 1 |
| Connectors (Slack, GitHub, Notion, etc.) | 1 |
| Consent-first, client-sanitized capture | 1 |
| Human console + memory wiki | 1 |
| LLM distillation + curator | 1 |
| MCP-native agent interface | 1 |
| GBrain synthesis layer (`gbrain think`) | 1 |
| GBrain self-wiring knowledge graph | 1 |
| GBrain dream cycle (overnight enrichment) | 1 |
| GBrain company brain (OAuth-scoped slices) | 1 |
| GBrain schema packs | 1 |

## Competitors (6)

| Entity | Sources |
|---|---|
| **GBrain (garrytan/gbrain)** — personal + company brain | 2 |
| Pinecone / pgvector category | 1 |
| Neo4j knowledge graphs | 1 |
| LangChain / LlamaIndex | 1 |
| Cloudflare Agent Memory | 1 |
| Hindsight-style distillation | 1 |

> GBrain is now the only competitor with multi-source evidence (gbrain research +
> YC RFS). Previous landscape entries were category placeholders from `plan.md`.

## Insights (5)

| Insight | Sources |
|---|---|
| Four memory pillars (working/semantic/episodic/procedural) | 1 |
| Just-in-time retrieval beats full-history in-context | 1 |
| YC RFS validates "company brain" category; names GBrain | 1 |
| GBrain has distribution lead (23k stars, YC CEO, OpenClaw native) | 1 |
| TeamShared (consent-first) vs GBrain (aggressive ingest) tension | 2 |

## Contradictions (1)

- **Consent-first capture** (TeamShared) **contradicts** **GBrain dream cycle /
  signal detector** (aggressive ingestion on every message). Both sides have
  provenance. This is a real product-philosophy fork, not a bug in the graph.

## Assumptions

- **Teams want cross-agent shared memory** — entire thesis at risk
- **Orgs will pay for shared agent context** — GBrain is MIT/open-source
- **Consent-first gates adoption** — GBrain's default is aggressive ingest
- **Connectors are the adoption lever** — GBrain already ships meeting/email/voice recipes
- **SSO/SAML/SOC2 gates deals** — GBrain targets 10-50 person OAuth teams first
- **Shared-by-default is desired** — GBrain scopes per-login slices
- **Humans browse the wiki** — GBrain optimizes agent-query (`think`), not browsing
- **Distillation quality is sufficient** — GBrain sets higher bar with gap analysis + eval CI
- **GBrain is the primary direct competitor** — positioning risk if buyers self-host
- **Synthesis + gap analysis required to win** — TeamShared recall returns records, not answers

## Next

- `discovery-query` — interrogate: "where does TeamShared win vs GBrain?"
- `tradeoff-frame` — consent-first vs aggressive ingest; managed vs self-hosted
- `interview-guide` — validate which ingestion philosophy buyers actually want

The graph is a map of what your corpus says, not a model of the world. It grows when your sources do.
