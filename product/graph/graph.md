# TeamShared — discovery graph

> **CORPUS HEALTH: DEVELOPING.** 20 sources (doc, research tagged types) plus untagged internal docs. Shipped-state (2026-07-12) now anchors what-is-built; still **zero user-research evidence** — no interviews, tickets, or support threads.


Generated 2026-07-13. Sources: 20. Types: doc, research.
Nodes: 185 · Edges: 113 · Assumptions surfaced: 19.

## Shipped product (from shipped-state-2026-07-12)

23 Feature nodes carry provenance from the canonical shipped-state doc:

- Asana-style projects with sections and status updates
- Audit logs for all memory and permission events
- Context compression MCP tools (context_compress/prepare/normalize/retrieve + CCR refs)
- Cross-agent shared recall by default on durable pillars
- Distiller worker: LLM summarizes closed sessions into durable memory
- Human console + continuously-updating memory wiki
- LLM distillation + curator synthesizing wiki pages
- MCP-native agent memory interface
- Memory explorer with keyword search and Ask the brain
- Multi-tenant org architecture
- OTP email sign-in multi-tenant console at /app
- Ontology console for entity types, link types, governed actions
- Optional Neo4j graph pillar for explicit entity relationships
- Optional chat-completions gateway with pre-LLM compression + enrichment
- Org work queue with assignees, dependencies, followers
- Public /memory status dashboard (no auth)
- Role-based access control + per-read permission checks
- Server-side ToolCallCaptureMiddleware + /sessions/turns ingest (capture not hook-dependent)
- Six memory pillars + optional graph (working/semantic/episodic/procedural/strategic/work + Neo4j)
- Skills (atomic how-tos) vs playbooks (composed flows)
- Strategic pillar: vision, mission, purpose, OKR cycles
- Unified curl install.sh agent onboarding
- memory_think synthesized answers with citations + gap analysis

## Segments (7)

| Segment | Distinct sources |
|---|---|
| Agents / agentic workflows (first-class identities) | 1 |
| Enterprise buyers | 1 |
| Founders building 'company brain' products (YC RFS category) | 1 |
| Knowledge workers wanting ambient desktop recall (screen + audio) | 1 |
| Multi-tenant organizations / teams | 1 |
| Power users running personal autonomous agents (OpenClaw/Hermes) | 1 |
| Teams shopping for a 'shared brain' across coding agents (Claude Code/Cursor/Codex/OpenClaw/Hermes) | 1 |

## Needs (10)

| Need | Distinct sources |
|---|---|
| Get synthesized answers with citations, not raw page lists | 1 |
| Know what the brain doesn't know yet (staleness / holes) | 1 |
| Memory layer that links documents and carries context across LLM calls | 1 |
| No cross-tenant memory leakage | 1 |
| Persistent recall without overwhelming the context window | 1 |
| Query what was true at a point in time (bi-temporal fact validity) | 1 |
| Recall anything seen or heard on the desktop without manual logging | 1 |
| Share memory across users, agents, projects, and tools | 1 |
| Sub-millisecond recall without LLM calls in the query path | 1 |
| Turn institutional knowledge into executable skills for AI automation | 1 |

## Pains (12)

| Pain | Distinct sources |
|---|---|
| AI-assisted code rot: duplication, dead code, undocumented load-bearing logic | 1 |
| Agent instruction files drift away from the real codebase | 1 |
| Agent loop iterations compound unsigned or unverified code changes | 1 |
| Coding agents amnesiac about everything that isn't code | 1 |
| Context rot from stuffing full history into the window | 1 |
| Critical company know-how scattered across heads, email, Slack, tickets | 1 |
| Every agent session starts cold with a prompt dump | 1 |
| Flat key-value memory with no distinction between facts and events | 1 |
| Forgetting what you saw, heard, or did on prior days | 1 |
| LLM calls are stateless — no memory of prior requests or documents | 1 |
| LLM calls during graph ingestion compound cost at scale | 1 |
| Per-agent memory silos: one engineer's agent learns nothing from another's | 1 |

## Features (74)

| Feature | Distinct sources |
|---|---|
| Asana-style projects with sections and status updates *shipped* | 2 |
| Audit logs for all memory and permission events *shipped* | 2 |
| Cognee Cloud managed SaaS (platform.cognee.ai) | 1 |
| Cognee MCP: 14 specialized tools (remember/recall/forget preferred) | 1 |
| Cognee induced ontologies during ingestion | 1 |
| Cognee ingest SKILL.md into dataset with improvement proposals | 1 |
| Cognee multi-user dataset-level isolation (tenants, roles, ACL) | 1 |
| Cognee recall auto-routing (summary, graph, temporal, coding-rules, lexical) | 1 |
| Cognee session cache with background improve bridge to permanent graph | 1 |
| Cognee triple-store architecture (relational + vector + graph) | 1 |
| Cognee v1.0 remember / recall / improve / forget lifecycle | 1 |
| Connectors (Slack, GitHub, Notion, Google Drive, Linear, MCP) | 1 |
| Context compression MCP tools (context_compress/prepare/normalize/retrieve + CCR refs) *shipped* | 2 |
| Cross-agent shared recall by default on durable pillars *shipped* | 2 |
| Distiller worker: LLM summarizes closed sessions into durable memory *shipped* | 2 |
| GBrain autonomous dream cycle (cron enrichment overnight) | 1 |
| GBrain company brain (per-user OAuth-scoped slices, leak-tested) | 1 |
| GBrain schema packs (typed page taxonomy, agent-evolvable) | 1 |
| GBrain self-wiring knowledge graph (zero LLM on write) | 1 |
| GBrain synthesis layer (gbrain think) with gap analysis | 1 |
| Graphiti: bi-temporal context graph with valid_from / invalid_at on every edge | 1 |
| Headroom CCR: Compress-Cache-Retrieve reversible compression (SQLite) | 1 |
| Headroom ContentRouter: per-type compression (JSON/code/logs/text/diffs) | 1 |
| Headroom MCP: headroom_compress / headroom_retrieve / headroom_stats | 1 |
| Headroom proxy: zero-code OpenAI/Anthropic-compatible local compression gateway | 1 |
| Hivemind: codify session traces into SKILL.md that propagates to team agents | 1 |
| Hivemind: every session prompt/tool-call/response captured as structured trace in Deep Lake | 1 |
| Human console + continuously-updating memory wiki *shipped* | 2 |
| LLM distillation + curator synthesizing wiki pages *shipped* | 2 |
| MCP-native agent memory interface *shipped* | 2 |
| Memory explorer with keyword search and Ask the brain *shipped* | 1 |
| Multi-tenant org architecture *shipped* | 3 |
| NEXO Brain: trust scoring + metacognitive guard + natural forgetting | 1 |
| Neo4j Agent Memory: POLE+O entities + reasoning traces (why the agent decided) | 1 |
| OTP email sign-in multi-tenant console at /app *shipped* | 2 |
| Ontology console for entity types, link types, governed actions *shipped* | 1 |
| Optional Neo4j graph pillar for explicit entity relationships *shipped* | 2 |
| Optional chat-completions gateway with pre-LLM compression + enrichment *shipped* | 2 |
| Org work queue with assignees, dependencies, followers *shipped* | 2 |
| Org/team/project/user/agent memory scopes | 1 |
| Palantir action types: governed writes with validation, side effects, audit | 1 |
| Palantir ontology: object types (nouns) + link types (relationships) + interfaces | 1 |
| PromptQL artifacts: plain language → tables, charts, reports, dashboards | 1 |
| PromptQL connectors: Postgres, Snowflake, BigQuery, Databricks, GitHub, Slack, Salesforce, GWorkspace | 1 |
| PromptQL delegates coding tasks to Claude Code or Codex on user's machine | 1 |
| PromptQL multiplayer AI: real-time thread with @-mentions and agent collaboration | 1 |
| PromptQL shared context wiki: captures domain knowledge as the team works | 1 |
| Public /memory status dashboard (no auth) *shipped* | 1 |
| RACT MCP consumer: mcp_servers in rootact.yaml, McpToolRegistry | 1 |
| RACT Root Knot: _ROOT_KNOT sentinel halts loop on unsigned drift | 1 |
| RACT anti-rot CLI: consolidate, novelty scan, auction, fence, whisper | 1 |
| RACT signed run receipts (JSON export for CI and cross-model QA) | 1 |
| Role-based access control + per-read permission checks *shipped* | 2 |
| Screenpipe MCP: query screen/audio history from Cursor and Claude Desktop | 1 |
| Screenpipe Pipes: trigger-based AI agents on captured data (meeting_ended, standup, CRM) | 1 |
| Screenpipe Teams: per-pipe YAML data permissions enforced at OS level (fleet MDM) | 1 |
| Screenpipe event-driven capture: accessibility tree + OCR fallback + audio transcription | 1 |
| Screenpipe on-device PII model: exclude-at-source + scrub cards/SSNs/keys before save | 1 |
| Server-side ToolCallCaptureMiddleware + /sessions/turns ingest (capture not hook-dependent) *shipped* | 3 |
| Six memory pillars + optional graph (working/semantic/episodic/procedural/strategic/work + Neo4j) *shipped* | 2 |
| Skills (atomic how-tos) vs playbooks (composed flows) *shipped* | 1 |
| Strategic pillar: vision, mission, purpose, OKR cycles *shipped* | 1 |
| Unified curl install.sh agent onboarding *shipped* | 1 |
| memnos proxy: deterministic capture by relaying Anthropic/OpenAI base URLs untouched | 1 |
| memnos: no LLM at query time + governance baked in (auth/ACL/audit/vault) | 1 |
| memobase: Postgres RLS per-user isolation + OAuth + cross-tool passport | 1 |
| memory-mcp: hybrid BM25 + vector with RRF + bounded feedback rerank | 1 |
| memory_think synthesized answers with citations + gap analysis *shipped* | 2 |
| mex ROUTER.md task-type → context file routing (~120-token anchor) | 1 |
| mex-mcp draft PR (#84): mex_check, mex_read_file, mex_log, mex_heartbeat | 1 |
| mex: 11 zero-token drift checkers (paths, deps, staleness, broken links) | 1 |
| multi-agent-memory: distinct fact vs event memory kinds | 1 |
| xChuCx/agent-memory: durable writes stage for human review (propose → apply) | 1 |
| xChuCx/agent-memory: git-native markdown, branch-aware, federation for cross-repo landscape stores | 1 |

## Outcomes (1)

| Outcome | Distinct sources |
|---|---|
| Evolve TeamShared from PoC to production for multi-tenant org customers | 1 |

## Competitors (25)

| Competitor | Distinct sources |
|---|---|
| Cloudflare Agent Memory (managed memory primitives) | 1 |
| Cognee (topoteretes/cognee) — graph+vector AI memory platform (~27.5k★) | 1 |
| GBrain (garrytan/gbrain) — personal + company brain for OpenClaw/Hermes | 2 |
| Graphiti (getzep, OSS) — bi-temporal context graphs on Neo4j/FalkorDB/Kuzu | 1 |
| Headroom (chopratejas/headroom) — context compression layer, 41k★, Apache 2.0 | 1 |
| Hindsight-style distillation sub-agents | 1 |
| Hivemind (activeloopai) — cloud-backed shared brain for Claude Code/OpenClaw/Codex/Cursor/Hermes/pi | 1 |
| LangChain / LlamaIndex memory modules | 1 |
| Letta (ex-MemGPT) — OS-paging metaphor, self-editing memory blocks | 1 |
| Mem0 — long-term memory layer for LLM applications/agents (55k★, OpenMemory MCP branch) | 1 |
| NEXO Brain (wazionapps) — local, trust scoring + forgetting + metacognitive guard | 1 |
| Neo4j Agent Memory Service — POLE+O entities + reasoning traces (55★) | 1 |
| Neo4j context/knowledge graphs | 1 |
| OpenClaw native memory (memory-core) — workspace markdown files + hybrid search | 1 |
| Pinecone (vector DB) / pgvector category | 1 |
| PromptQL — multiplayer AI over live data with shared context wiki | 1 |
| RACT (LucRoot/RACT) — CLI agentic coding harness + anti-rot verifiers (~3★) | 1 |
| Screenpipe (screenpipe/screenpipe) — ambient desktop capture + MCP, 19k★, YC S26 | 1 |
| Zep / Graphiti — temporal knowledge graph (bi-temporal, 71% LongMemEval) | 1 |
| memnos (thameema) — self-hosted, no LLM at query, governance baked in | 1 |
| memobase.ai — cross-tool memory passport, Postgres RLS, OAuth | 1 |
| memory-mcp (isaacriehm) — Postgres+pgvector, RRF hybrid search, OAuth bridge | 1 |
| mex (mex-memory/mex) — repo-scoped markdown scaffold + drift CLI (~1.1k★) | 1 |
| multi-agent-memory (CMPSBL) — cross-machine fact/event store for OpenClaw/Claude Code/n8n mesh | 1 |
| xChuCx/agent-memory — git-native markdown, branch-aware, federation | 1 |

## Insights (31)

| Insight | Distinct sources |
|---|---|
| Agent memory splits into four pillars (working/semantic/episodic/procedural) | 1 |
| Bi-temporal validity is the legitimate Graphiti moat for point-in-time queries; no rival matches it | 1 |
| Clean-room activation validates engineering baseline, not design-partner fit *shipped* | 1 |
| Cognee and GBrain are comparable OSS scale (~27k vs ~23k stars) | 1 |
| Cognee is Tier-1 direct memory competitor (not adjacent like mex/Headroom) | 1 |
| Cognee ships managed cloud SKU — closer to TeamShared GTM than GBrain OSS-only | 1 |
| External connectors (Slack, GitHub, Notion, Linear) not shipped as first-class sync *shipped* | 1 |
| GBrain has distribution lead: 23k stars, YC CEO author, native OpenClaw/Hermes wiring | 1 |
| Headroom is orthogonal to durable memory: shrinks current prompt, does not persist org brain | 1 |
| Hivemind ships the same skill-codification thesis as teamshared's skills pillar — but auto-mines from traces | 1 |
| Human approvals console route not shipped despite pending_approval data model *shipped* | 1 |
| Just-in-time retrieval beats keeping full history in-context | 1 |
| MCP is the de facto 'USB-C for memory' standard; all serious players expose memory through MCP | 1 |
| Multiple rivals (multi-agent-memory, memnos, teamshared MemoryKind) independently converge on distinguishing facts from events | 1 |
| No memory system wins on more than 3 of 8 dimensions; each leads on a distinct axis | 1 |
| OpenClaw harness + TeamShared MCP is layered complement (local scratch + org brain) | 1 |
| OpenClaw memory-wiki claims/evidence layer peers TeamShared curator wiki + ontology | 1 |
| OpenClaw native memory is Tier-3 harness-adjacent personal memory — not multi-tenant org brain | 1 |
| Palantir Foundry ontology is architectural reference, not a memory competitor | 1 |
| PromptQL data-live permissions are a genuine connector moat TeamShared does not yet claim | 1 |
| PromptQL is a data-first AI analyst, not a reusable agent-memory substrate | 1 |
| Primary Tier-1 memory competitors in corpus: GBrain and Cognee *shipped* | 1 |
| RACT competes with Cursor harness surface where TeamShared plugin attaches | 1 |
| RACT harness + TeamShared MCP is complementary (consumer + provider) | 1 |
| RACT is Tier-3 adjacent coding harness — not org memory competitor | 1 |
| Screenpipe is orthogonal to org brain: ambient device capture, not shared multi-tenant memory | 1 |
| Shipped differentiation: governance + team workflow over raw graph depth *shipped* | 1 |
| YC RFS validates 'company brain' as a venture category; names GBrain as reference implementation | 1 |
| Zep's LongMemEval lead over Mem0 (71% vs 49%) is methodologically disputed | 1 |
| mex addresses repo hygiene; TeamShared addresses org recall — complementary axis | 1 |
| mex is Tier-3 repo-scoped adjacent — not a multi-tenant org brain | 1 |

## Assumptions (19)

### Solo OpenClaw users can stay on MEMORY.md without needing hosted org brain

*Risk if wrong:* If teams never graduate from file memory to TeamShared MCP, OpenClaw distribution becomes a ceiling — GBrain or native memory-core wins by default.

### Bi-temporal fact validity is not needed for TeamShared's buyer (timestamp-only facts suffice)

*Risk if wrong:* If buyers want point-in-time queries ('what did Sarah own in Q1'), Graphiti/Zep win decisively on a 22-point LongMemEval gap. The curator compensates by rewriting pages but cannot answer historical queries.

### Default cross-agent visibility (shared brain) is what users want

*Risk if wrong:* GBrain company brain scopes per-login slices. If isolation-by-default wins, TeamShared's open recall default is a trust risk.

### Engineering clean-room pass is enough to start design-partner outreach **NEW (shipped-state)**

*Risk if wrong:* Clean-room activation passed in ~10–11 minutes but explicitly does not substitute design-partner validation — market fit remains unproven.

### Explicit memory_skill_set is enough; an auto-trace-to-skill miner is not needed

*Risk if wrong:* Hivemind ships the auto-mine-from-traces loop now and pitches it as the headline differentiator. If buyers expect skills to compound automatically, TeamShared's manual skill authoring feels like a notepad vs Hivemind's database-backed brain.

### GBrain or Cognee is the primary direct competitor (not the broader field)

*Risk if wrong:* Positioning and roadmap sequencing. Cognee (~27.5k★) matches GBrain (~23k★) as Tier-1 graph/memory platform with managed cloud; Hivemind ships auto-skill-mining; Mem0/Zep/Letta have massive adoption. GBrain-only framing misses Cognee in the same MCP slot.

### Humans will actually browse the memory wiki/console

*Risk if wrong:* GBrain optimizes for agent-query (`gbrain think`) not human browsing. Wiki investment may not match how winners get used.

### LLM distillation yields durable, low-noise memory worth recalling

*Risk if wrong:* GBrain's gap analysis and eval CI gates set a higher bar for synthesis quality than raw distillation.

### MCP-native memory is sufficient without first-class external connector sync **NEW (shipped-state)**

*Risk if wrong:* If teams expect Slack/GitHub/Notion as first-class sync (listed as not shipped), adoption stalls at "another MCP server" without integration breadth.

### Manual skill/playbook authoring beats auto-trace mining for target buyers **NEW (shipped-state)**

*Risk if wrong:* Shipped-state lists auto-trace-to-skill mining (Hivemind-style) as not shipped; if buyers expect skills to compound automatically, manual authoring feels inferior.

### Orgs will pay for 'shared agent context' as infrastructure

*Risk if wrong:* Pricing/GTM viability; GBrain is MIT/open-source, Mem0/Zep/Letta all monetize cloud tiers ($19/$25/$249). TeamShared willingness-to-pay unvalidated.

### Teams evaluating shared-brain products may shortlist PromptQL alongside TeamShared

*Risk if wrong:* If buyers conflate 'shared context wiki' with 'shared agent memory', PromptQL's data-live + BI artifact story could capture deals that TeamShared wants.

### SSO/SAML/SOC2 gate the deals worth chasing

*Risk if wrong:* GBrain company-brain tutorial targets 10-50 person teams with OAuth — may win design partners before TeamShared enterprise phase.

### Slack/GitHub/Notion/etc. connectors are the adoption lever

*Risk if wrong:* GBrain already ingests meetings/email/tweets/voice via recipes. Connector roadmap may be table stakes, not differentiation.

### Synthesis + gap analysis is required to win (not just hybrid recall)

*Risk if wrong:* Product investment. TeamShared recall returns records; GBrain `think` returns answers. Missing synthesis may feel like a search engine.

### TeamShared doesn't need a published benchmark number to compete

*Risk if wrong:* Mem0 published ECAI 2025; Zep claims 71% LongMemEval. Without a number, the strategic KPI ('reliable enough to trust') is asserted, not proven — buyers comparing platforms have no objective recall-quality signal.

### TeamShared governance (work queue, OKRs, ontology console) differentiates vs Cognee without graph parity

*Risk if wrong:* If buyers pick memory on graph ontology depth or star count alone, Cognee wins; approvals UI is also not shipped despite data model.

### Teams actually want cross-agent shared memory

*Risk if wrong:* The entire product thesis. If teams don't want a shared agent brain, every roadmap phase is built on sand.

### Teams can govern agent writes without a human approvals console UI **NEW (shipped-state)**

*Risk if wrong:* If buyers require in-console review queues for guarded ingestion, the missing /app/approvals route blocks enterprise adoption despite the data model existing.

## Edge summary

| Edge type | Count |
|---|---|
| assumes | 19 |
| belongs-to | 6 |
| blocks | 2 |
| competes-with | 25 |
| contradicts | 2 |
| evidences | 2 |
| experiences | 12 |
| requests | 4 |
| supports | 32 |

## Meta notes

- Graphify 2026-07-12: ingested shipped-state-2026-07-12.md (type: doc) — canonical shipped product state from codebase.
- teamshared-product.md is a symlink to PRODUCT.md; read as untagged product context doc.
- Skipped sources/README.md (workspace boilerplate) and sources/interview-template.md (empty template, not evidence).
- Eighteen sources: six internal product docs (incl. shipped-state) + nine external research artifacts + design-partner-tracker + clean-room-run. Still zero user-interview or support-ticket evidence.
- Untagged sources (no YAML type): clean-room-run-2026-07-11.md, design-partner-tracker.md, memory-wiki-plan.md, plan.md, prod-plan.md, teamshared-agents.md, teamshared-product.md, teamshared-readme.md.
- shipped-state supersedes prod-plan.md for what-is-built; prod-plan remains roadmap/aspirational.
- Six memory pillars + optional graph, context compression MCP, work queue + projects, skills vs playbooks, ontology console, OTP multi-tenant console (no /app/approvals), distiller/curator workers, optional gateway — all evidenced from shipped-state + readme + agents.
- Primary Tier-1 competitors reaffirmed: GBrain, Cognee. Adjacent: Headroom, Screenpipe, mex, RACT, OpenClaw native memory (harness-local file memory), PromptQL (multiplayer AI + shared wiki).
- Graphify 2026-07-13: ingested promptql-research.md — PromptQL multiplayer AI + shared wiki; data-live connectors + per-user permissions; Tier-2 adjacent competitor in shared-brain category.
- New assumptions from shipped-state gaps: approvals UI deferred, connectors not blocking, design-partner validation still needed, manual skills vs auto-mine.
