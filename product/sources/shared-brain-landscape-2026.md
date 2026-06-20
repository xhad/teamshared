---
type: research
title: "Shared brain / agent-memory landscape — June 2026"
author: web research (mem0/zep/letta/hivemind/memobase/memnos/graphiti/neo4j-agent-memory/xChuCx-agent-memory)
origin: https://mem0.ai/blog/state-of-ai-agent-memory-2026
captured: 2026-06-19
note: >
  External landscape research across the agent-memory / "shared brain" category.
  Compiled from public marketing pages, GitHub READMEs, and third-party
  comparison posts. NOT user research — these are vendor and analyst claims.
  Treat as multi-source competitive intelligence, still single-perspective
  (no buyers interviewed).
---

# Shared brain / agent-memory landscape — June 2026

Captured 2026-06-19 from public web research. Surveys four tiers of
agent-memory / "shared brain" MCP servers as of June 2026. Each section
preserves the vendor's own positioning language so the graph can quote it.

## Tier 1 — Hosted memory platforms (the well-funded incumbents)

### Mem0 (mem0.ai)

> "Mem0 is a long-term memory layer for LLM applications and AI agents that
> persists across/across sessions and users."

> "OpenMemory is Mem0's local-first memory layer for developers who want
> persistent memory across AI tools. It runs as an MCP-compatible memory
> server and works with Claude Desktop, Cursor, Windsurf, VS Code, and other
> MCP-compatible agents."

Pricing (mem0.ai/pricing, captured 2026-06-19):

> "Free / Unlimited, 10,000 [memories], 1,000 [retrievals]"
> "Starter / $19 Month / Unlimited, 50,000, 5,000"
> "Growth / $79/month / Unlimited, 200,000, 20,000"
> "Pro / $249/month / Unlimited, 500,000, 50,000"

Benchmark positioning (mem0.ai/blog/state-of-ai-agent-memory-2026):

> "The Mem0 research paper published at ECAI 2025 (arXiv:2504.19413)
> established the first broad head-to-head comparison of ten memory
> approaches... Mem0's new algorithm significantly raised that baseline."

Scale claim:

> "Mem0 wins on speed of adoption and ecosystem (~55k GitHub stars as of May
> 2026)."

### Zep / Graphiti (getzep.com)

> "Zep takes a different structural bet. Rather than flat vector storage, it
> builds a temporal knowledge graph using their open-source Graphiti library."

> "Zep + Graphiti win on bi-temporality and score 71.2% on LongMemEval versus
> Mem0's 49% — a twenty-two percentage point gap."

> "Graphiti's primary and default backend is Neo4j version 5.26 or higher."

Pricing:

> "Free / $0 / 1,000 credits/month — barely enough to test the API."
> "Flex / $25/month — full Graphiti engine, temporal graph, entity resolution."
> "Flex Plus / up to ~$475 at higher volumes"

### Letta (formerly MemGPT)

> "MemGPT, now rebranded as Letta, introduced an idea that felt ahead of its
> time... treat the LLM like an operating system managing its own memory.
> There's a 'main context' (RAM — what's in the prompt right now), a 'recall
> store' (recent conversation history), and an 'archival store' (external
> long-term storage)."

> "Memory blocks can also be shared between multiple agents. By attaching
> the same block to different agents, you can create powerful multi-agent
> systems where agents collaborate through shared memory."

Pricing:

> "Free / $0 / Up to 3 managed agents, BYOK"
> "Pro / $20/mo / Up to 20 stateful agents"

## Tier 2 — "Shared brain" MCP servers (direct rivals to the pitch)

### Hivemind (activeloopai/hivemind)

> "One brain for all your agents."
> "Auto-learning, cloud-backed shared brain for Claude Code • OpenClaw •
> Codex • Cursor • Hermes • pi agents."

> "Hivemind doesn't just remember. It mines your team's traces for repeated
> patterns and codifies them into reusable skills that propagate back into
> every agent on the team. The agent your junior engineer used this morning
> is sharper because of what your senior engineer's agent figured out last
> week."

> "Capture → Codify → Propagate → Compound. Every coding-agent interaction
> (prompt, tool call, response) is captured as a structured trace in
> Deeplake. A background worker mines traces for repeated patterns and
> codifies them into `SKILL.md` files, scoped to your workspace."

Adoption:

> "The project has garnered over 1,100 GitHub stars in its first day."

### memobase.ai

> "Memobase MCP = persistent shared memory."
> "PostgreSQL Row-Level Security ensures your memory is your own."

> "Memobase is a persistent memory layer for AI agents that leverages the
> Model Context Protocol (MCP) to provide shared, long-term context across
> disparate tools like Claude, Cursor, and Windsurf."

Tools surface:

> "The Memobase MCP server exposes three powerful tools... save_memory,
> search_memories, get_user_profiles."

### memnos (thameema/memnos)

> "memnos is a self-hosted memory server for AI agents. Your conversations
> are captured, distilled into facts, and recalled in later sessions —
> across Claude Code, Cursor, Windsurf, Codex, or anything that speaks MCP,
> REST, or an OpenAI/Anthropic-compatible base URL."

> "It runs on one PostgreSQL + pgvector database (no second vector store, no
> graph database), uses no LLM at query time, and ships with governance —
> token auth, namespace ACLs, audit log, and an encrypted secret vault — in
> the open-source build."

> "Deterministic (any base-URL client) — `memnos proxy`: point any OpenAI- or
> Anthropic-compatible client at the proxy... It relays every request
> untouched (streaming included, keys forwarded, never stored) and captures
> both sides of each completed exchange."

### memory-mcp (isaacriehm/memory-mcp)

> "memory-mcp is a Model Context Protocol server that gives AI agents
> durable, searchable memory backed by PostgreSQL and pgvector."

> "search_memory | Hybrid vector + BM25 search with Reciprocal Rank
> Fusion. Supports optional, bounded feedback rerank behind a kill switch."

### NEXO Brain (wazionapps/nexo)

> "NEXO Brain — Shared brain for AI agents. Persistent memory, semantic RAG,
> natural forgetting, metacognitive guard, trust scoring, 150+ MCP tools."

> "Fully local and free, no external dependencies."

### multi-agent-memory (CMPSBL)

> "Multi-Agent Memory gives your AI agents a shared brain that works across
> machines, tools, and frameworks. Store a fact from Claude Code on your
> laptop, recall it from an OpenClaw agent on your server, and get a briefing
> from n8n — all through the same memory system."

> "Existing solutions are either single-machine only, require paid cloud
> services, or treat memory as a flat key-value store without understanding
> that a fact and an event are fundamentally different things."

## Tier 3 — Git-native / repo-scoped memory

### xChuCx/agent-memory (Go)

> "Local, git-native project memory for AI coding agents. One MCP call in,
> structured memory updates out — current task state, decisions,
> conventions, pitfalls, per-module facts. Branch-aware. Secret-safe.
> Byte-preserving."

> "No cloud, no vector DB — Markdown is the source of truth and git is the
> sync. Three MCP tools + a full CLI."

> "Federation lets it reference shared, git-pinned, read-only 'landscape'
> stores, so an agent designing a cross-service feature sees the surrounding
> system map."

> "durable changes stage for human review (review --diff → apply) instead of
> landing silently; and secrets/PII are scanned out before anything is
> written."

## Tier 4 — Graph-first / temporal knowledge graphs

### Graphiti (getzep/graphiti)

> "Graphiti is a framework for building and querying temporal context graphs
> for AI agents. Unlike static knowledge graphs, Graphiti's context graphs
> track how facts change over time, maintain provenance to source data, and
> support both prescribed and learned ontology."

> "A key feature is Graphiti's bi-temporal model, tracking when an event
> occurred and when it was ingested. Every graph edge (or relationship)
> includes explicit validity intervals (t_valid, t_invalid)."

### Neo4j Agent Memory Service

> "The project implements three memory types: short-term (conversation
> history), long-term (facts and entities extracted via a POLE+O model
> covering Person, Object, Location, Event, and Organization entities), and
> reasoning memory (decision traces and tool usage audits). That reasoning
> layer is unique. No other tool in this comparison stores why the agent made
> a decision, which matters for debugging and compliance."

> "neo4j-agent-memory in February 2026. With 55 GitHub stars, it is the
> least-known tool in this comparison."

## Category-level claims (from third-party analyses)

### MCP as the de facto standard

> "Model Context Protocol — 'USB-C for memory' proposed by Anthropic in
> November 2024 — has become the de facto standard for agent ↔ external
> memory store communication. OpenMemory MCP from Mem0, Anthropic Memory
> Tool, Graphiti MCP server, Neo4j Agent Memory Service — all expose memory
> through MCP."

### Benchmark gap (Zep vs Mem0, disputed)

> "Zep achieves 9[8].% on DMR (Deep Memory Retrieval)... 71.2% on
> [LongMemEval] with GPT-4o. Mem0 stops at 49%... are the subject of a
> methodological dispute — a corrected [calculation] indicates a score
> [lower] than Zep initially [reported]."

### Cost comparison (widemem.ai, April 2026)

> "AI memory costs range from $0/mo (widemem, LangMem, Cognee self-hosted)
> to $249/mo (Mem0 Pro) to $475/mo (Zep Flex Plus) before you count LLM API
> calls, embeddings, or infrastructure."

> "the biggest hidden cost across the field is LLM calls during ingestion:
> graph-construction approaches make several calls per memory add, which
> compounds at scale."

### No system wins on more than 3 of 8 dimensions

> "No system wins in more than three of the eight dimensions. Mem0 wins on
> speed of adoption and ecosystem (~55k GitHub stars as of May 2026). Zep +
> Graphiti win on bi-temporality... Letta wins on self-editing memory and
> sleep-time compute. LangMem wins if you're already using LangGraph."