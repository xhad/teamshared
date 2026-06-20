# TeamShared — discovery graph

> **CORPUS HEALTH: THIN.** Eight sources: five internal product-intent docs
> plus three external research artifacts (YC RFS, GBrain competitor research,
> shared-brain-landscape-2026). There is still **zero user-research evidence**
> — no interviews, tickets, or support threads. The new landscape source is
> multi-source vendor/analyst competitive intelligence, still single-perspective
> (no buyers interviewed).

Generated 2026-06-19. Sources: 8. Types: research, prd, memo, doc.
Nodes: 88 · Edges: 48 · Assumptions surfaced: 12.

## Segments (6)

| Segment | Distinct sources |
|---|---|
| Multi-tenant organizations / teams | 1 |
| Enterprise buyers | 1 |
| Agents / agentic workflows | 1 |
| Founders building "company brain" (YC RFS) | 1 |
| Power users running OpenClaw/Hermes agents | 1 |
| Teams shopping for a "shared brain" across coding agents | 1 |

## Needs (7)

| Need | Sources |
|---|---|
| Share memory across users, agents, projects, tools | 2 |
| Persistent recall without overwhelming context window | 1 |
| No cross-tenant memory leakage | 1 |
| Synthesized answers with citations (not raw page lists) | 1 |
| Know what the brain doesn't know yet (gap analysis) | 1 |
| Turn institutional knowledge into executable AI skills | 2 |
| **Query what was true at a point in time (bi-temporal fact validity)** *new* | 1 |
| **Sub-millisecond recall without LLM calls in the query path** *new* | 1 |

## Pains (6)

| Pain | Sources |
|---|---|
| Context rot from stuffing full history into window | 1 |
| Coding agents amnesiac about non-code knowledge | 1 |
| Company know-how scattered across heads, email, Slack | 1 |
| **Per-agent memory silos: one engineer's agent learns nothing from another's** *new* | 1 |
| **Flat key-value memory with no distinction between facts and events** *new* | 1 |
| **LLM calls during graph ingestion compound cost at scale** *new* | 1 |

## Features (22)

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
| **Five memory pillars (working/semantic/episodic/procedural/strategic + work)** *new* | 1 |
| **Server-side ToolCallCaptureMiddleware + /sessions/turns ingest** *new* | 1 |
| GBrain synthesis layer (`gbrain think`) | 1 |
| GBrain self-wiring knowledge graph | 1 |
| GBrain dream cycle (overnight enrichment) | 1 |
| GBrain company brain (OAuth-scoped slices) | 1 |
| GBrain schema packs | 1 |
| **Hivemind: codify session traces into SKILL.md that propagates to team agents** *new* | 1 |
| **Hivemind: every session prompt/tool-call/response captured in Deep Lake** *new* | 1 |
| **memobase: Postgres RLS per-user isolation + OAuth + cross-tool passport** *new* | 1 |
| **memnos: no LLM at query time + governance baked in** *new* | 1 |
| **memnos proxy: deterministic capture by relaying base URLs untouched** *new* | 1 |
| **memory-mcp: hybrid BM25 + vector with RRF + bounded feedback rerank** *new* | 1 |
| **NEXO Brain: trust scoring + metacognitive guard + natural forgetting** *new* | 1 |
| **multi-agent-memory: distinct fact vs event memory kinds** *new* | 1 |
| **xChuCx/agent-memory: git-native markdown, branch-aware, federation** *new* | 1 |
| **xChuCx/agent-memory: durable writes stage for human review** *new* | 1 |
| **Graphiti: bi-temporal context graph with valid_from / invalid_at** *new* | 1 |
| **Neo4j Agent Memory: POLE+O entities + reasoning traces** *new* | 1 |

## Competitors (14)

| Entity | Sources |
|---|---|
| **GBrain (garrytan/gbrain)** — personal + company brain | 2 |
| **Mem0** — long-term memory layer (55k★, OpenMemory MCP) *new* | 1 |
| **Zep / Graphiti** — temporal knowledge graph (71% LongMemEval) *new* | 1 |
| **Letta (ex-MemGPT)** — OS-paging, self-editing memory blocks *new* | 1 |
| **Hivemind (activeloopai)** — cloud-backed shared brain *new* | 1 |
| **memobase.ai** — cross-tool memory passport, Postgres RLS *new* | 1 |
| **memnos (thameema)** — self-hosted, no LLM at query, governance *new* | 1 |
| **memory-mcp (isaacriehm)** — Postgres+pgvector, RRF *new* | 1 |
| **NEXO Brain (wazionapps)** — local, trust scoring + forgetting *new* | 1 |
| **multi-agent-memory (CMPSBL)** — cross-machine fact/event store *new* | 1 |
| **xChuCx/agent-memory** — git-native markdown, federation *new* | 1 |
| **Graphiti (getzep, OSS)** — bi-temporal context graphs *new* | 1 |
| **Neo4j Agent Memory Service** — POLE+O + reasoning traces (55★) *new* | 1 |
| Pinecone / pgvector category | 1 |
| Neo4j knowledge graphs | 1 |
| LangChain / LlamaIndex | 1 |
| Cloudflare Agent Memory | 1 |
| Hindsight-style distillation | 1 |

> GBrain remains the only competitor with multi-source evidence (gbrain
> research + YC RFS). The 2026 landscape adds 11 named rivals — Hivemind is
> the most direct threat because it ships the same skill-codification thesis
> as TeamShared's skills pillar but with auto-mining from traces.

## Insights (8)

| Insight | Sources |
|---|---|
| Four memory pillars (working/semantic/episodic/procedural) | 1 |
| Just-in-time retrieval beats full-history in-context | 1 |
| YC RFS validates "company brain" category; names GBrain | 1 |
| GBrain has distribution lead (23k stars, YC CEO, OpenClaw native) | 1 |
| **MCP is the de facto "USB-C for memory" standard** *new* | 1 |
| **No system wins on >3 of 8 dimensions; each leads on a distinct axis** *new* | 1 |
| **Zep's 71% LongMemEval lead over Mem0 (49%) is methodologically disputed** *new* | 1 |
| **Bi-temporal validity is the legitimate Graphiti moat for point-in-time queries** *new* | 1 |
| **Hivemind ships the same skill-codification thesis but auto-mines from traces** *new* | 1 |
| **Multiple rivals converge on distinguishing facts from events** *new* | 1 |

## Contradictions (1)

- **Mem0 vs Zep benchmark dispute** — Zep claims 71.2% LongMemEval vs Mem0's
  49%, but the calculation is contested (corrected scores reportedly lower).
  The contradiction is in the public record; downstream `discovery-query` and
  `assumption-audit` must treat both numbers as disputed, not settled.

## Assumptions

Pre-existing (10):

- **Teams want cross-agent shared memory** — entire thesis at risk
- **Orgs will pay for shared agent context** — GBrain is MIT/open-source; Mem0/Zep/Letta all monetize cloud tiers ($19/$25/$249)
- **Connectors are the adoption lever** — GBrain already ships meeting/email/voice recipes
- **SSO/SAML/SOC2 gates deals** — GBrain targets 10-50 person OAuth teams first
- **Shared-by-default is desired** — GBrain scopes per-login slices
- **Humans browse the wiki** — GBrain optimizes agent-query (`think`), not browsing
- **Distillation quality is sufficient** — GBrain sets higher bar with gap analysis + eval CI
- **GBrain is the primary direct competitor** — Hivemind ships the same skill-codification thesis; Mem0/Zep/Letta have orders of magnitude more adoption
- **Synthesis + gap analysis required to win** — TeamShared recall returns records, not answers

New from the 2026 landscape (3):

- **Bi-temporal fact validity is not needed** — risk: if buyers want point-in-time queries, Graphiti/Zep win on a 22-point LongMemEval gap; the curator compensates by rewriting pages but cannot answer historical queries.
- **Explicit `memory_skill_set` is enough; an auto-trace-to-skill miner is not needed** — risk: Hivemind ships the auto-mine-from-traces loop now and pitches it as the headline differentiator.
- **TeamShared doesn't need a published benchmark number to compete** — risk: Mem0 published ECAI 2025; Zep claims 71%. Without a number, the strategic KPI ("reliable enough to trust") is asserted, not proven.

## Next

- `assumption-audit` — re-triage the 13 assumptions; the three new ones
  (bi-temporal, auto-skill-mine, benchmarks) directly threaten the
  strategic KPI ("reliable enough to trust").
- `discovery-query` — interrogate: "where does TeamShared win vs Hivemind
  on the skills pillar?" and "does the broader 2026 landscape invalidate
  the GBrain-only positioning?"
- `interview-guide` — validate which of bi-temporal / auto-skill-mine /
  published-benchmark buyers actually care about.

The graph is a map of what your corpus says, not a model of the world. It grows when your sources do.
