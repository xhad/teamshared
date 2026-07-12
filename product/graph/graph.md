# TeamShared — discovery graph

> **CORPUS HEALTH: DEVELOPING.** Fourteen sources: five internal product-intent docs
> plus nine external research artifacts (YC RFS, GBrain, shared-brain-landscape-2026,
> Headroom, Screenpipe, **mex**, **Palantir ontology**, **Cognee**, **RACT**). There is still
> **zero user-research evidence** — no interviews, tickets, or support threads.

Generated 2026-07-11. Sources: 14. Types: research, prd, memo, doc.
Nodes: 141 · Edges: 78 · Assumptions surfaced: 13.

## Segments (7)

| Segment | Distinct sources |
|---|---|
| Multi-tenant organizations / teams | 1 |
| Enterprise buyers | 1 |
| Agents / agentic workflows | 1 |
| Founders building "company brain" (YC RFS) | 1 |
| Power users running OpenClaw/Hermes agents | 1 |
| Teams shopping for a "shared brain" across coding agents | 1 |
| Knowledge workers wanting ambient desktop recall | 1 |

## Needs (10)

| Need | Sources |
|---|---|
| Share memory across users, agents, projects, tools | 2 |
| Persistent recall without overwhelming context window | 1 |
| No cross-tenant memory leakage | 1 |
| Synthesized answers with citations (not raw page lists) | 1 |
| Know what the brain doesn't know yet (gap analysis) | 1 |
| Turn institutional knowledge into executable AI skills | 2 |
| Query what was true at a point in time (bi-temporal fact validity) | 1 |
| Sub-millisecond recall without LLM calls in the query path | 1 |
| Recall anything seen or heard on the desktop without manual logging | 1 |
| **Memory layer linking documents across LLM calls** *new* | 1 |

## Pains (12)

| Pain | Sources |
|---|---|
| Context rot from stuffing full history into window | 1 |
| Coding agents amnesiac about non-code knowledge | 1 |
| Company know-how scattered across heads, email, Slack | 1 |
| Per-agent memory silos | 1 |
| Flat key-value memory with no distinction between facts and events | 1 |
| LLM calls during graph ingestion compound cost at scale | 1 |
| Forgetting what you saw, heard, or did on prior days | 1 |
| **LLM calls are stateless — no memory of prior requests** *new* | 1 |
| **Agent instruction files drift from the real codebase** *new* | 1 |
| **Every agent session starts cold with a prompt dump** *new* | 1 |
| **AI-assisted code rot (duplication, dead code)** *new* | 1 |
| **Agent loops compound unsigned code changes** *new* | 1 |

## Features (54)

| Feature | Sources |
|---|---|
| Multi-tenant org architecture | 2 |
| Org/team/project/user/agent memory scopes | 1 |
| RBAC + per-read permission checks | 1 |
| Audit logs | 2 |
| Connectors (Slack, GitHub, Notion, etc.) | 1 |
| Human console + memory wiki | 1 |
| LLM distillation + curator | 1 |
| MCP-native agent interface | 1 |
| Five memory pillars (working/semantic/episodic/procedural/strategic + work) | 1 |
| Server-side ToolCallCaptureMiddleware + /sessions/turns ingest | 1 |
| GBrain synthesis layer (`gbrain think`) | 1 |
| GBrain self-wiring knowledge graph | 1 |
| GBrain dream cycle (overnight enrichment) | 1 |
| GBrain company brain (OAuth-scoped slices) | 1 |
| GBrain schema packs | 1 |
| Hivemind: codify session traces into SKILL.md | 1 |
| memobase: Postgres RLS + OAuth + cross-tool passport | 1 |
| memnos: no LLM at query time + governance | 1 |
| memory-mcp: hybrid BM25 + vector with RRF | 1 |
| NEXO Brain: trust scoring + metacognitive guard | 1 |
| multi-agent-memory: distinct fact vs event memory kinds | 1 |
| xChuCx/agent-memory: git-native markdown, federation | 1 |
| Graphiti: bi-temporal context graph | 1 |
| Neo4j Agent Memory: POLE+O entities + reasoning traces | 1 |
| Headroom ContentRouter + CCR + proxy + MCP | 1 |
| Screenpipe event-driven capture + Pipes + MCP | 1 |
| **Cognee v1.0 remember/recall/improve/forget** *new* | 1 |
| **Cognee triple-store (relational + vector + graph)** *new* | 1 |
| **Cognee MCP: 14 tools** *new* | 1 |
| **Cognee Cloud managed SaaS** *new* | 1 |
| **Cognee session→graph improve bridge** *new* | 1 |
| **Cognee recall auto-routing** *new* | 1 |
| **Cognee induced ontologies** *new* | 1 |
| **Cognee SKILL.md ingest + improvement proposals** *new* | 1 |
| **Cognee dataset-level multi-user isolation** *new* | 1 |
| **mex: 11 zero-token drift checkers** *new* | 1 |
| **mex ROUTER.md context routing** *new* | 1 |
| **mex-mcp draft (PR #84)** *new* | 1 |
| **Palantir action types (governed writes)** *new* | 1 |
| **Palantir object/link types + interfaces** *new* | 1 |
| **RACT Root Knot continuity sentinel** *new* | 1 |
| **RACT anti-rot CLI (consolidate, auction, fence)** *new* | 1 |
| **RACT signed run receipts** *new* | 1 |
| **RACT MCP consumer (rootact.yaml)** *new* | 1 |

## Competitors (23)

| Entity | Sources | Tier |
|---|---|---|
| **GBrain (garrytan/gbrain)** — personal + company brain | 2 | Tier 1 |
| **Cognee (topoteretes/cognee)** — graph+vector platform, ~27.5k★, MCP + Cloud *new* | 1 | Tier 1 |
| Mem0 — long-term memory layer (55k★) | 1 | Tier 2 |
| Zep / Graphiti — temporal knowledge graph | 1 | Tier 2 |
| Letta (ex-MemGPT) — OS-paging memory blocks | 1 | Tier 2 |
| Hivemind (activeloopai) — cloud-backed shared brain | 1 | Tier 1 |
| memobase.ai — cross-tool memory passport | 1 | Tier 2 |
| memnos — self-hosted, no LLM at query | 1 | Tier 2 |
| memory-mcp — Postgres+pgvector, RRF | 1 | Tier 2 |
| NEXO Brain — local, trust scoring | 1 | Tier 2 |
| multi-agent-memory — cross-machine fact/event store | 1 | Tier 2 |
| xChuCx/agent-memory — git-native markdown | 1 | Tier 3 |
| **mex (mex-memory/mex)** — repo scaffold + drift CLI, ~1.1k★ *new* | 1 | Tier 3 |
| Graphiti (getzep, OSS) — bi-temporal context graphs | 1 | Tier 2 |
| Neo4j Agent Memory Service — POLE+O + traces | 1 | Tier 2 |
| Pinecone / pgvector category | 1 | — |
| Neo4j knowledge graphs | 1 | — |
| LangChain / LlamaIndex | 1 | — |
| Cloudflare Agent Memory | 1 | — |
| Hindsight-style distillation | 1 | — |
| Headroom — context compression, 41k★ (adjacent) | 1 | Tier 3 |
| Screenpipe — ambient desktop capture + MCP (adjacent) | 1 | Tier 3 |
| **RACT (LucRoot/RACT)** — CLI coding harness + anti-rot, ~3★ *new* | 1 | Tier 3 |

> **Cognee** joins **GBrain** as a Tier-1 direct memory competitor with comparable
> OSS scale (~27.5k vs ~23k stars) and managed cloud GTM. See
> `knowledge/cognee-competitor-analysis.md`. **mex** is Tier-3 repo-scaffold
> adjacent — see `knowledge/mex-competitor-analysis.md`. **Palantir Foundry
> ontology** is architectural reference only — see `knowledge/palantir-ontology-analysis.md`.
> **RACT** is Tier-3 adjacent coding harness (MCP consumer) — see
> `knowledge/ract-competitor-analysis.md`.

## Insights (21)

| Insight | Sources |
|---|---|
| Four memory pillars (working/semantic/episodic/procedural) | 1 |
| Just-in-time retrieval beats full-history in-context | 1 |
| YC RFS validates "company brain" category; names GBrain | 1 |
| GBrain has distribution lead (23k stars, YC CEO, OpenClaw native) | 1 |
| MCP is the de facto "USB-C for memory" standard | 1 |
| No system wins on >3 of 8 dimensions; each leads on a distinct axis | 1 |
| Zep's 71% LongMemEval lead over Mem0 is methodologically disputed | 1 |
| Bi-temporal validity is Graphiti's moat for point-in-time queries | 1 |
| Hivemind ships auto-trace-to-skill mining | 1 |
| Multiple rivals converge on distinguishing facts from events | 1 |
| Headroom is orthogonal: shrinks current prompt, not org brain | 1 |
| Screenpipe is orthogonal: ambient device capture, not org brain | 1 |
| **Cognee is Tier-1 direct — not adjacent like mex/Headroom** *new* | 1 |
| **Cognee and GBrain are comparable OSS scale peers** *new* | 1 |
| **Cognee managed cloud GTM closer to TeamShared than GBrain OSS** *new* | 1 |
| **mex is Tier-3 repo-scoped adjacent** *new* | 1 |
| **mex complements TeamShared (repo hygiene vs org recall)** *new* | 1 |
| **Palantir ontology is architectural reference, not memory competitor** *new* | 1 |
| **RACT is Tier-3 adjacent coding harness** *new* | 1 |
| **RACT + TeamShared MCP is complementary (consumer + provider)** *new* | 1 |
| **RACT competes with Cursor harness surface** *new* | 1 |

## Contradictions (1)

- **Mem0 vs Zep benchmark dispute** — Zep claims 71.2% LongMemEval vs Mem0's
  49%, but the calculation is contested. Treat both numbers as disputed.

## Assumptions (13)

Pre-existing (updated):

- **Teams want cross-agent shared memory** — entire thesis at risk
- **Orgs will pay for shared agent context** — GBrain MIT; Cognee Cloud + Mem0/Zep/Letta cloud tiers
- **Connectors are the adoption lever** — GBrain already ships meeting/email/voice recipes
- **SSO/SAML/SOC2 gates deals** — GBrain/Cognee target OAuth teams first
- **Shared-by-default is desired** — GBrain scopes per-login; Cognee isolates per dataset
- **Humans browse the wiki** — GBrain/Cognee optimize agent-query
- **Distillation quality is sufficient** — GBrain gap analysis + Cognee improve loop set higher bar
- **GBrain or Cognee is the primary direct competitor** *updated* — Cognee (~27.5k★) now co-equal Tier-1 threat alongside GBrain
- **Synthesis + gap analysis required to win** — TeamShared recall returns records

From 2026 landscape (3):

- **Bi-temporal fact validity is not needed** — Graphiti/Zep win on point-in-time queries
- **Explicit memory_skill_set is enough; auto-trace-to-skill miner not needed** — Hivemind ships auto-mine
- **Published benchmark not needed to compete** — Mem0 ECAI 2025; Zep 71% claims

New from Cognee (1):

- **Governance (work, OKRs, approvals, capture) differentiates vs Cognee without graph parity** — risk: buyers pick on stars/ontology depth alone

## Next

- `assumption-audit` — re-triage 13 assumptions; Cognee adds a second Tier-1 front alongside GBrain
- `discovery-query` — "Does Cognee Cloud or self-host win design-partner evals vs TeamShared?"
- `discovery-query` — "Do buyers conflate repo scaffold (mex) with company brain (Cognee/GBrain)?"
- `interview-guide` — validate governance wedge vs graph-depth buyers

The graph is a map of what your corpus says, not a model of the world. It grows when your sources do.
