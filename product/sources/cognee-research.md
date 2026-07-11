---
type: research
title: "Cognee — AI memory platform research"
author: topoteretes/cognee (public repo + docs.cognee.ai)
origin: https://docs.cognee.ai/
captured: 2026-07-11
note: >
  External product/architecture research from Cognee public docs, GitHub README,
  MCP package README, and API reference index. Vendor/marketing claims — not user
  research. Cognee is a graph+vector memory *platform* with OSS, MCP, and managed
  cloud — closer to GBrain than mex/Headroom.
---

# Cognee — AI memory platform research

Captured 2026-07-11 from [docs.cognee.ai](https://docs.cognee.ai/),
[topoteretes/cognee](https://github.com/topoteretes/cognee) (~27.5k GitHub stars,
Apache-2.0, Python primary, v1.2.x dev releases Jul 2026). Homepage:
[cognee.ai](https://www.cognee.ai). Managed product:
[platform.cognee.ai](https://platform.cognee.ai).

Cognee's category: **open-source AI memory platform for agents** — ingest
documents/code/URLs, build a self-hosted knowledge graph with vector search,
query via `remember` / `recall` / `improve` / `forget`, expose through MCP, REST,
Python SDK, TypeScript SDK, and Rust client. Ships both OSS self-host and
**Cognee Cloud** managed SaaS.

## Positioning

From docs introduction:

> "Give Cognee your documents, and it creates a graph of raw information,
> extracted concepts, and meaningful relationships you can query."

> "When you call an LLM, each request is stateless… You need a memory layer that
> can link your documents together and create the right context for every LLM call."

From GitHub README:

> "Cognee is the open-source AI memory platform that gives AI agents persistent
> long-term memory across sessions."

> "Easily Build Company Brain - unify data from various sources in one place and
> enable Agents with your domain knowledge"

Compared to TeamShared: Cognee pitches **graph+vector knowledge infrastructure**
with induced ontologies and pluggable stores — not TeamShared's five-pillar
semantic/episodic/procedural/skill/strategic model, but substantial overlap on
MCP agent memory, session bridging, skills ingestion, multi-user isolation, and
a human UI.

## Scale & distribution

| Signal | Value | Source |
|---|---|---|
| GitHub stars | ~27.5k (Jul 2026) | github.com/topoteretes/cognee |
| Forks | ~2.7k | same |
| Contributors | ~180 | same |
| License | Apache-2.0 | LICENSE |
| SDK runs/month (marketing) | 5M+ | cognee.ai homepage |
| Accelerator | Berkeley Xcelerator (cited on site) | cognee.ai |
| Research paper | arXiv:2505.24478 (graph–LLM interface) | README |
| Community | Discord, r/AIMemory, cognee-community plugins | README |

Integrations ship for **OpenClaw** (`@cognee/cognee-openclaw`), **Claude Code**
plugin, **Cursor**, **Codex**, **Continue**, **Cline** — same harness surface
TeamShared targets.

## Core operations (v1.0)

Four high-level operations replace the legacy `add` → `cognify` → `search` →
`memify` pipeline for most users:

### `.remember` — ingest

- **Permanent memory** (no `session_id`): full pipeline — normalize → chunk →
  extract entities/relationships → embed → optional immediate `improve` pass.
- **Session memory** (`session_id`): fast cache write; with `self_improvement=True`
  (default) bridges to permanent graph in background via `improve`.
- Accepts raw text, file paths, HTTP/S URLs, S3 paths, `DataItem` metadata
  wrappers, and many file formats (txt/md/pdf/images/audio/docs with extras).
- Dataset-scoped (`dataset_name`, default `main_dataset`).

### `.recall` — query

- Auto-routing by default: classifies query and picks retrieval strategy
  (summary, graph context, temporal, coding-rules, lexical).
- Graph-backed by default for permanent memory (`GRAPH_COMPLETION` fallback).
- Session-aware: with `session_id`, searches session cache first, falls through
  to graph; results tagged `source`: `session` | `graph` | `trace` | `graph_context`.
- Explicit `query_type` override available.

### `.improve` — enrich / bridge

- Enriches existing graph (triplet embeddings, derived retrieval structures).
- **Session bridging**: feedback weights on graph elements, persist session Q&A,
  agent traces, distill session lessons into `session_learnings`, optional truth
  subspace, sync enriched graph back to session cache.
- Optional `build_global_context_index` for dataset-level summary buckets.

### `.forget` — delete

- Remove data item, dataset, or all user-owned memory.

Legacy lower-level ops (`add`, `cognify`, `search`, `memify`) remain for custom
pipelines.

## Architecture

From architecture docs — **three complementary stores**:

| Store | Role |
|---|---|
| **Relational** | Document metadata, chunks, provenance |
| **Vector** | Embeddings for semantic similarity |
| **Graph** | Entities and relationships (knowledge graph) |

Default local backends are lightweight; production swaps include Postgres,
LanceDB, Kuzu, Neo4j-class graph stores (see setup docs).

Ingestion flow (docs diagram): raw documents → chunks → extracted entities →
derived concepts → **induced ontologies** → searchable memory via
remember / improve / recall.

## Multi-user mode

`ENABLE_BACKEND_ACCESS_CONTROL` (default on v0.5.0+ when storage supports it):

- **Dataset-level isolation** for graph/vector stores — each dataset routed to
  its own physical backend in multi-user mode.
- **Tenants** group users sharing dataset permissions (not a DB boundary).
- **Permissions**: read/write/share/delete per dataset; roles; ACL APIs.
- **Isolated recall**: retrieval scoped to datasets the authenticated user can read.

Cognee Cloud adds RBAC, collaboration, managed Postgres + LanceDB + Kuzu.

## Cognee Cloud (managed)

From cloud overview:

| | Hosted Cloud | Local UI (free) |
|---|---|---|
| Account | Required | No |
| Infrastructure | Managed | Your machine |
| Collaboration | Yes | No |
| Same UI & pipelines | Yes | Yes |

Features: web UI (upload, graph explore, search), Python SDK via `cognee.serve()`,
sync local ↔ cloud, agent framework connections, multi-tenancy.

**Note:** Cognee MCP and Cognee Cloud are documented as *separate systems* with
different APIs/auth — MCP can target Cloud via API base URL + key.

## MCP surface

From [MCP overview](https://docs.cognee.ai/cognee-mcp/mcp-overview.md):

- **14 specialized tools** for memory management, code intelligence, data ops.
- Prefer v1.0 tools: `remember`, `recall`, `forget` (legacy tools for
  lower-level control).
- **Standalone mode**: MCP server runs full Cognee pipeline locally with own DB.
- **API mode**: MCP connects to centralized Cognee backend — shared knowledge
  graph across clients/team members.
- `cognee-mcp` package bundles full Cognee — no separate install required.
- Transports: stdio (default), SSE, Streamable HTTP.
- Client guides: Cursor, Claude Desktop/Code, Codex, Continue, Cline.

From cognee-mcp README (minimal memory API variant):

- `remember` — session or permanent graph memory
- `recall` — query with optional session/search controls
- `forget` — delete dataset or all owned memory

## REST API highlights (beyond core ops)

From API index — enterprise-shaped surface:

- Auth: login, register, API keys, password reset
- Datasets: CRUD, status, graph visualization, raw data download, schema
- Permissions: tenants, roles, user-role assignment, dataset ACL grant/revoke
- Ontologies: upload/list/delete for cognify grounding
- Skills: `ingest-skill` (SKILL.md), list/get dataset skills, skill-improvement proposals
- Schema: inventory, provenance visualization, infer-schema from samples
- Sync: local ↔ Cognee Cloud
- OpenAI-compatible responses endpoint with function calling
- OTEL / audit traits mentioned in README marketing

## Skills & ontology

- **Skills ingestion**: REST `POST` ingest SKILL.md markdown into dataset;
  list/get skills with full procedure bodies; skill-improvement proposals.
- **Ontology**: upload ontology files for cognify; LLM infer-schema from samples;
  induced ontologies during ingestion (core concept).
- Custom graph schema + prompt per dataset (`get/update dataset schema`).

## Self-improvement & learning

`improve` with session IDs implements a feedback loop:

1. Apply feedback weights to graph elements used in retrieval
2. Persist session Q&A and agent traces into permanent graph
3. Distill gated session guidance into `session_learnings` documents
4. Optional truth-subspace anchors for hybrid reranking
5. Sync enriched relationships back to session cache

Marketing claims: "Persistent and Learning Agents - learn from feedback, context
management, cross-agent knowledge sharing"

## What Cognee does NOT emphasize (vs TeamShared)

From public docs — no equivalent surfaced for:

- Human work queue (`work_*`) with assignees and status workflow
- Strategic OKR / initiative memory pillar
- Agent write approval queue for humans
- OTP email console for non-technical teammates
- Server-side ToolCallCaptureMiddleware across harnesses
- Explicit "shared brain read-unscoped by default" agent attribution model
- Context compression middleware for bulky tool output (Headroom-style)

Capture appears agent-driven (`remember` calls, session traces) rather than
automatic server-side transcript ingest.

## Competitive tier placement

| Tier | Examples | Cognee fit |
|---|---|---|
| **Tier 1 — direct memory brain** | GBrain, Cognee, TeamShared | Primary competitor |
| **Tier 2 — framework/SDK** | Mem0, LangMem | Cognee is full product above these |
| **Tier 3 — adjacent layer** | mex, Headroom, Screenpipe | Different axis |

Cognee and GBrain are the two highest-star open-source "agent memory platform"
peers in this corpus (~27k vs ~23k stars). Both ship MCP + company-brain
narrative. GBrain leads on synthesis/gap-analysis UX and YC distribution;
Cognee leads on graph ontology infrastructure, managed cloud SKU, and format
breadth.

## Open questions (not in docs)

- Pricing for Cognee Cloud (not captured)
- Head-to-head recall quality vs GBrain / TeamShared on same corpus
- Whether design partners choose Cognee Cloud vs self-host vs TeamShared SaaS
- How many production teams run Cognee multi-user vs single-user datasets
- Overlap/conflict when both Cognee MCP and TeamShared MCP are configured in Cursor
