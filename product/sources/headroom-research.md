---
type: research
title: "Headroom — context compression layer research"
author: chopratejas/headroom (public repo + docs)
origin: https://github.com/chopratejas/headroom
captured: 2026-06-20
note: >
  External product/architecture research from Headroom's public README, llms.txt,
  architecture docs, and shallow source-code inspection (v0.26.0). Vendor claims
  on token savings and benchmark accuracy — not user research. Headroom is a
  *context compression* product, not a durable memory brain; it sits upstream
  of the LLM and shrinks what agents read/write.
---

# Headroom — context compression layer research

Captured 2026-06-20 from [chopratejas/headroom](https://github.com/chopratejas/headroom)
(~41k GitHub stars, Apache 2.0, Python 78.8% + Rust 16.7%). Latest release v0.26.0.

Headroom's category: **context optimization / token compression** — not long-term
memory storage. It compresses tool outputs, logs, files, RAG chunks, and
conversation context *before* they reach the LLM, with claimed 60–95% token
reduction while preserving answer quality.

## Positioning

> "The context compression layer for AI agents"

> "Compress tool outputs, logs, files, and RAG chunks before they reach the LLM.
> 60–95% fewer tokens, same answers. Library, proxy, MCP server."

> "Headroom compresses everything your AI agent reads — tool outputs, logs, RAG
> chunks, files, and conversation history — before it reaches the LLM. Same
> answers, fraction of the tokens."

Compared to memory platforms (Mem0, Zep, TeamShared): Headroom does not pitch
durable team knowledge, org scoping, or episodic recall — it intercepts the
*current* prompt context and makes it smaller.

## Four entry points (same pipeline)

| Mode | How | Code changes |
|---|---|---|
| **Library** | `from headroom import compress` | Minimal — compress messages before API call |
| **Proxy** | `headroom proxy --port 8787` | Zero — point client at localhost proxy |
| **Agent wrap** | `headroom wrap claude\|codex\|cursor\|aider\|copilot` | One command |
| **MCP server** | `headroom_compress`, `headroom_retrieve`, `headroom_stats` | MCP client config |

Also ships TypeScript SDK (`npm install headroom-ai`) and Docker image
(`ghcr.io/chopratejas/headroom:latest`).

## High-level architecture

From official architecture docs — Headroom sits between application and LLM:

```
YOUR APPLICATION
       │
       v
HEADROOM CLIENT
  ANALYZE (Parser) → TRANSFORM (Pipeline) → CALL (API)
       │
       v
OPENAI / ANTHROPIC / GOOGLE
```

> "Headroom sits between your application and the LLM provider. It intercepts
> messages, compresses them intelligently, and forwards the optimized request.
> The response comes back unchanged."

## Transform pipeline (core mechanism)

Canonical lifecycle stages (from `headroom/pipeline.py`):

> `Setup` → `Pre-Start` → `Post-Start` → `Input Received` → `Input Cached` →
> `Input Routed` → `Input Compressed` → `Input Remembered` → `Pre-Send` →
> `Post-Send` → `Response Received`

**Transform order** (from `headroom/transforms/pipeline.py` docstring):

1. **CacheAligner** — normalize prefix for provider KV-cache hits
2. **ContentRouter** — detect content type, route to specialized compressor

> "Phase B PR-B1 retired the IntelligentContextManager / RollingWindow 'drop
> messages from history' stage. Live-zone-only compression is the sole strategy
> going forward — message-list mutation no longer happens in the pipeline."

### Stage 1: CacheAligner

> "Extracts dynamic content (dates, UUIDs, session tokens) from your system
> prompt and moves it to the end. This stabilizes the prefix so provider caches
> (Anthropic `cache_control`, OpenAI prefix caching) can hit on repeated calls."

Example from docs:

```
Before: "You are helpful. Current Date: 2024-12-15"  → cache miss daily
After:  "You are helpful." [stable prefix]
        "[Context: Current Date: 2024-12-15]" [dynamic tail]
```

Overhead: sub-millisecond.

### Stage 2: ContentRouter

From `headroom/transforms/content_router.py` module docstring:

> "Analyzes content and routes it to the optimal compressor. Handles mixed
> content by splitting, routing each section, and reassembling."

Supported compressors:

- **SmartCrusher** — JSON arrays (statistical sampling)
- **CodeCompressor** — AST-aware via tree-sitter / ast-grep (Python, JS, Go, Rust, Java, C++)
- **SearchCompressor** — grep/ripgrep results
- **LogCompressor** — build/test output
- **KompressCompressor** — plain text via HuggingFace `kompress-base` ONNX model
- **DiffCompressor** — diffs

Routing strategy:

> "1. Use source hint if available (highest confidence)
>  2. Check for mixed content (split and route sections)
>  3. Detect content type (JSON, code, search, logs, text)
>  4. Route to appropriate compressor
>  5. Reassemble and return with routing metadata"

ContentRouter accounts for 91–98% of pipeline latency on average per benchmarks docs.

### SmartCrusher (JSON)

> "Parses JSON arrays in tool outputs
>  Runs field-level statistical analysis (variance, uniqueness, change points)
>  Selects a representative subset using the Kneedle algorithm on bigram coverage
>  Preserves errors, anomalies, and distribution boundaries unconditionally
>  Factors out constant fields shared by all items"

Retention split: 30% from array start (schema), 15% from end (recency), 55% by
importance score. Error items always kept.

Typical savings (architecture docs):

| Content | Savings |
|---|---|
| JSON arrays of dicts | 83–95% |
| JSON arrays of strings | 60–90% |
| Build/test logs | 85–94% |
| HTML (trafilatura) | ~95% |

### Kompress-base (text)

> "Kompress-base — our HuggingFace model, trained on agentic traces."

Uses ONNX runtime (`onnxruntime`); optional `[ml]` extra. Requires download from
`huggingface.co` unless pre-cached.

## CCR: Compress-Cache-Retrieve (reversibility)

> "When SmartCrusher compresses a tool output or Intelligent Context drops
> messages, the original content is stored in a local compression cache. If the
> LLM needs the full data, it can request retrieval via a `ccr_retrieve` tool
> call. This makes compression reversible."

```
Compress:  1000 items  ->  15 items  (stored original in CCR)
Cache:     Hash-indexed local store (SQLite)
Retrieve:  LLM calls ccr_retrieve("abc123")  ->  original 1000 items
```

> "Unlike traditional lossy compression, CCR guarantees that every piece of
> original data remains accessible. You get 70-90% token savings with zero risk
> of permanent data loss."

Proxy exposes `/ccr/retrieve` endpoints; MCP exposes `headroom_retrieve`.

## TOIN: Tool Output Intelligence Network

> "TOIN learns compression patterns across sessions and users. When a tool is
> used repeatedly, TOIN builds up statistics about which fields matter, which
> items get retrieved, and what compression strategies work best."

Cold start falls back to statistical heuristics.

## What Headroom does NOT touch

From architecture docs:

> * **User messages**: Never compressed (the user's intent must be preserved exactly)
> * **System prompts**: Content preserved; only dynamic parts are relocated for caching
> * **Code**: Passes through unchanged unless tree-sitter AST compression is explicitly enabled
> * **Model responses**: Returned unchanged from the provider
> * **Short content**: Tool outputs under 200 tokens pass through (overhead exceeds savings)

## Output token reduction (separate feature)

Shrinks what the model *writes back*, not just input:

> "Verbosity steering — appends a short 'be terse, don't restate context' note
> to the end of the system prompt"
> "Effort routing — when a turn is just the model resuming after a tool result,
> it dials the model's thinking effort down."

Enabled via `HEADROOM_OUTPUT_SHAPER=1` on the proxy. Savings reported as
estimated with confidence intervals (counterfactual — never sees unshaped output).

## Proxy server

FastAPI/uvicorn proxy (`headroom/proxy/server.py` — 3600+ lines). Intercepts
OpenAI-compatible and Anthropic API formats, runs compression pipeline on
request messages, forwards to upstream provider.

Features:

- Per-session `CompressionCache` instances
- CCR retrieve endpoints
- Provider-specific cache hints (Anthropic `cache_control`, OpenAI prefix, Google CachedContent)
- Output shaper and effort routing
- Hot-sync runtime env via `POST /admin/runtime-env` (for `headroom wrap`)

## MCP integration

MCP tools: `headroom_compress`, `headroom_retrieve`, `headroom_stats`.

From `headroom/integrations/mcp/server.py`:

> "MCP tool outputs are the PERFECT use case for Headroom. They're often large
> (100s-1000s of items), structured (JSON), and contain mostly low-relevance
> data with a few critical items (errors, matches)."

Also ships `HeadroomMCPCompressor`, per-tool profiles (Slack search vs DB query
vs file listing), and client wrapper that compresses tool outputs automatically.

## Memory subsystem (separate from TeamShared-style brain)

Headroom has its own optional **memory** module (`headroom/memory/`):

> "Simple, zero-config memory for AI applications"

Backends:

> - "local" (default): SQLite + HNSW + InMemoryGraph. No setup required.
> - "qdrant-neo4j": Qdrant + Neo4j. Requires Docker services.

API: `Memory.save()`, `Memory.search()`, `with_memory(OpenAI())` wrapper,
`with_memory_tools()` for LLM-extracted facts.

This is **per-project/session compression-adjacent memory**, not multi-tenant
org brain. Docs emphasize "No cross-project bleed (GH #462)."

## Cross-agent features

### SharedContext

> "When agents hand off to each other, context gets replayed in full.
> SharedContext compresses what moves between agents, using Headroom's existing
> CCR architecture."

`ctx.put("research", big_output)` → other agent gets compressed version;
`ctx.get("research", full=True)` for originals.

### Cross-agent memory (marketing)

README claims "shared store across Claude, Codex, Gemini, auto-dedup" when
running with `--memory` flag on wrap. Local SQLite + vector index.

## headroom learn

> "Mines failed sessions, writes corrections to `CLAUDE.md` / `AGENTS.md`"

Plugin architecture (`headroom/learn/plugins/`): claude, codex, gemini adapters.
Offline LLM analysis of conversation logs → generates agent guidance markdown.
Also supports `--verbosity` to learn terseness preferences from past sessions.

## Agent compatibility

| Agent | `headroom wrap` | Notes |
|---|---|---|
| Claude Code | ✅ | `--memory`, `--code-graph` |
| Codex | ✅ | shares memory with Claude |
| Cursor | ✅ | prints config — paste once |
| Aider | ✅ | starts proxy + launches |
| Copilot CLI | ✅ | subscription mode via OAuth |
| OpenClaw | ✅ | ContextEngine plugin |

Any OpenAI-compatible client works via proxy. MCP-native: `headroom mcp install`.

## Benchmark claims (vendor)

Token savings on real workloads (README):

| Workload | Before | After | Savings |
|---|---|---|---|
| Code search (100 results) | 17,765 | 1,408 | **92%** |
| SRE incident debugging | 65,694 | 5,118 | **92%** |
| GitHub issue triage | 54,174 | 14,761 | **73%** |
| Codebase exploration | 78,502 | 41,254 | **47%** |

Accuracy on benchmarks (README):

| Benchmark | Baseline | Headroom | Delta |
|---|---|---|---|
| GSM8K | 0.870 | 0.870 | ±0.000 |
| TruthfulQA | 0.530 | 0.560 | +0.030 |
| SQuAD v2 | — | 97% | 19% compression |
| BFCL | — | 97% | 32% compression |

Reproduce: `python -m headroom.evals suite --tier 1`

## Compared to adjacent tools (Headroom's own framing)

| Product | Scope | Local | Reversible |
|---|---|---|---|
| **Headroom** | All context — tools, RAG, logs, files, history | Yes | Yes (CCR) |
| RTK | CLI command outputs | Yes | No |
| lean-ctx | CLI, MCP, editor rules | Yes | No |
| Compresr / Token Co. | Text via hosted API | No | No |
| OpenAI Compaction | Conversation history | No | No |

> "Headroom ships with the excellent RTK binary for shell-output rewriting"
> "Headroom can also use lean-ctx as the selected CLI context tool;
> set `HEADROOM_CONTEXT_TOOL=lean-ctx`"

## Rust core

`crates/` directory — Rust components compiled via maturin for Python wheel.
ONNX runtime for Kompress model inference. `headroom/onnx_runtime.py` bridges
Python ↔ Rust.

## Relationship to TeamShared (analyst note — not Headroom claim)

Headroom and TeamShared operate on **orthogonal layers**:

- **Headroom**: shrinks the *current prompt* (tool outputs, logs, context window)
  before the LLM call. Stateless compression with local CCR cache.
- **TeamShared**: persists *durable* semantic/episodic/procedural memory across
  sessions, orgs, and agents. Recall, distillation, wiki, work queue.

Potential integration point: TeamShared MCP tool results and `memory_recall`
hits could pass through Headroom compression before entering agent context —
Headroom's MCP integration doc explicitly targets this pattern.

Potential tension: TeamShared's value is *full-fidelity recall* with citations;
Headroom's value is *lossy-but-reversible compression*. CCR mitigates loss but
adds retrieval round-trips.

## Tech stack summary

- Python 3.10+ package `headroom-ai` (maturin/Rust build)
- FastAPI proxy, MCP server
- SQLite CCR cache, optional Qdrant+Neo4j memory
- HuggingFace Kompress-base ONNX model
- tree-sitter / ast-grep for code compression
- OpenTelemetry instrumentation
- 1649 commits, 156 releases, active CI
