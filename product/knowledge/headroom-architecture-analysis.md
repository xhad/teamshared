# Headroom architecture analysis (mogkit)

Generated via mogkit workflow: source capture → `discovery-query` (×3) →
`tradeoff-frame`. Source: `product/sources/headroom-research.md` (public
docs + v0.26.0 code inspection). Corpus health: **thin** (single-source
vendor/architecture research — no user interviews, no hands-on benchmark
reproduction in this corpus).

---

## Executive summary

**Headroom is not a TeamShared competitor — it is an adjacent context-compression
layer.** Where TeamShared persists durable team knowledge (semantic, episodic,
procedural pillars, org scoping, distillation), Headroom shrinks the *current*
prompt — tool outputs, logs, RAG chunks, files — before the LLM call. Same
session, fewer tokens, with reversible retrieval via CCR.

The architecture is a **two-stage transform pipeline** (CacheAligner →
ContentRouter) with six specialized compressors, a local SQLite CCR cache, and
four deployment modes (library, proxy, agent wrap, MCP). It ships optional
cross-agent memory and `headroom learn` (failure mining → AGENTS.md), but
those are compression-adjacent features, not a multi-tenant org brain.

For TeamShared product planning: Headroom addresses **context rot** (a pain
already in the graph) without replacing recall, wiki, or work queue. The
interesting question is whether TeamShared should **integrate** Headroom
upstream of MCP tool results and recall hits, not whether to compete with it.

---

## How Headroom works (architecture deep dive)

This section synthesizes the source corpus and code inspection. It is
engineering documentation, not mogkit graph output.

### 1. Placement in the stack

```
Agent (Cursor, Claude Code, Codex, …)
    │  messages + tool results + system prompt
    ▼
┌─────────────────────────────────────────────────────────┐
│ HEADROOM (local process)                                │
│                                                         │
│  Parser ──► TransformPipeline ──► Provider cache hints  │
│              │                                          │
│              ├─ CacheAligner (prefix stabilization)     │
│              └─ ContentRouter                           │
│                   ├─ SmartCrusher (JSON arrays)         │
│                   ├─ CodeCompressor (AST / tree-sitter) │
│                   ├─ LogCompressor / SearchCompressor   │
│                   ├─ DiffCompressor                     │
│                   └─ KompressCompressor (ONNX ML text)  │
│                                                         │
│  CCR store (SQLite, hash-indexed) ◄── originals kept    │
└─────────────────────────────────────────────────────────┘
    │  compressed messages + optional ccr_retrieve tool
    ▼
LLM provider (Anthropic / OpenAI / Google / Bedrock / …)
```

Headroom **never modifies model responses** on the way back (except optional
output-shaping that steers verbosity/effort on the *next* turn). User messages
are never compressed — only tool outputs and compressible assistant context.

### 2. Canonical pipeline lifecycle

From `headroom/pipeline.py`, every request (library, SDK, or proxy) emits
events through stable stages:

| Stage | What happens |
|---|---|
| `input_received` | Raw messages arrive |
| `input_cached` | Content-addressed cache lookup (skip re-compress if seen) |
| `input_routed` | ContentRouter detects types per message block |
| `input_compressed` | Compressors run; CCR stores originals |
| `input_remembered` | Optional memory subsystem writes |
| `pre_send` | Provider-specific cache hints applied |
| `post_send` / `response_received` | Metrics, output-shaper bookkeeping |

Extensions hook via `on_pipeline_event()` and Python entry points
(`headroom.pipeline_extension`).

### 3. CacheAligner — make provider KV caches hit

Dynamic content (dates, UUIDs, session tokens) in system prompts busts
Anthropic/OpenAI prefix caches. CacheAligner extracts dynamic fragments to
the *tail* of the message, leaving a stable prefix:

```
Before: "You are helpful. Current Date: 2024-12-15"
After:  "You are helpful." + "[Context: Current Date: 2024-12-15]"
```

Overhead: sub-millisecond. Works alongside compression — SmartCrusher reduces
token count; CacheAligner makes repeated calls cheaper on cached prefix tokens.

### 4. ContentRouter — the core routing brain

`ContentRouter` (`headroom/transforms/content_router.py`) is the highest-latency
stage (91–98% of pipeline time). For each compressible block it:

1. Checks **source hints** (tool name, MIME, caller metadata) — highest confidence
2. Detects **mixed content** — splits prose + JSON + code fences, routes each section
3. Runs **content type detection** (regex + optional Magika ML classifier)
4. Delegates to the matching compressor
5. **Reassembles** with routing metadata (`router:smart_crusher`, etc.)

**Important v0.26.0 change:** RollingWindow / IntelligentContextManager
(message dropping from history) was **retired**. Compression is now
*live-zone-only* — tool outputs and eligible blocks shrink in place; the
message list length stays the same.

### 5. Compressor catalog

| Compressor | Input | Mechanism | Typical savings |
|---|---|---|---|
| **SmartCrusher** | JSON arrays | Field-level stats, Kneedle sampling on bigram coverage; keeps errors/anomalies; 30% head + 15% tail + 55% scored | 83–95% |
| **CodeCompressor** | Source code | AST via tree-sitter / ast-grep; preserves imports, signatures, types | Opt-in; 0% default pass-through |
| **LogCompressor** | Build/test logs | Pattern clustering | 85–94% |
| **SearchCompressor** | grep/rg output | Dedup + relevance sampling | 60–90% |
| **KompressCompressor** | Plain text | HuggingFace `kompress-base` ONNX model trained on agentic traces | Variable |
| **DiffCompressor** | Unified diffs | Hunk summarization | High on large diffs |

**Pass-through rules:** Content under ~200 tokens skips compression (overhead
> savings). Already-compact grep lines and raw Python source show 0% in
benchmarks unless code compression is explicitly enabled.

### 6. CCR — reversible compression

When SmartCrusher replaces 1000 JSON items with 15, the original lands in a
**CompressionCache** (SQLite, hash-indexed, LRU eviction):

```
Compress → store original under hash key → embed marker in compressed text
Retrieve → LLM calls ccr_retrieve(hash) → proxy returns full original
```

The proxy injects a `ccr_retrieve` tool transparently; the client never sees
the round-trip. This is Headroom's answer to "lossy compression might hide
the FATAL line" — the model can pull the full payload on demand.

TeamShared analogy: CCR is like keeping the full episode in Postgres while
showing the agent a distilled summary — except Headroom does it per tool call
with TTL, not per org with curator review.

### 7. TOIN — learned compression preferences

**Tool Output Intelligence Network** accumulates per-tool statistics across
sessions: which fields get retrieved, which compression strategies worked,
which items the model asked CCR to expand. Feeds back into SmartCrusher scoring
and (when enabled) IntelligentContext importance. Cold start uses heuristics only.

### 8. Four deployment modes

| Mode | Entry | Use case |
|---|---|---|
| **Library** | `compress(messages, model=…)` | Inline in any Python/TS app |
| **Proxy** | `headroom proxy --port 8787` | Zero code change; point API base URL |
| **Wrap** | `headroom wrap cursor` | One-command agent launcher + proxy |
| **MCP** | `headroom_compress` / `headroom_retrieve` / `headroom_stats` | Compress MCP tool results at the host |

The proxy (`headroom/proxy/server.py`, FastAPI) handles OpenAI + Anthropic
formats, WebSocket for Codex, zstd bodies, per-session compression caches,
and hot-reload of env vars via `POST /admin/runtime-env`.

### 9. Adjacent subsystems (not the core compression loop)

**Memory module** (`headroom/memory/`): optional SQLite+HNSW+graph or
Qdrant+Neo4j backends. `with_memory(OpenAI())` auto-extracts facts. Per-project
scope — explicitly no cross-project bleed.

**SharedContext**: in-process compressed handoffs between agents (`put`/`get`
with CCR-backed full retrieval).

**headroom learn**: offline plugin-based session analysis → writes
`CLAUDE.md` / `AGENTS.md` corrections. Overlaps TeamShared's skills/distillation
thesis but targets *token-waste prevention rules*, not durable org memory.

**Output shaper** (`HEADROOM_OUTPUT_SHAPER=1`): verbosity steering + effort
routing on routine post-tool turns. Reports counterfactual output savings with
confidence intervals.

### 10. Tech stack

- Python 3.10+ (`headroom-ai` on PyPI), Rust core via maturin (`crates/`)
- ONNX Runtime for Kompress; tree-sitter/ast-grep for code
- FastAPI + uvicorn proxy; MCP via `mcp` package
- OpenTelemetry metrics; optional Qdrant/Neo4j for production memory mode

---

## discovery-query #1: What problem does Headroom solve?

> Corpus health: **thin**. Single-source vendor docs.

### Findings

**1. Headroom targets context-window cost, not durable memory**
- *Confidence: Single-source*
- "Compress tool outputs, logs, files, and RAG chunks before they reach the LLM" — `headroom-research.md`
- "Headroom compresses everything your AI agent reads … before it reaches the LLM" — `headroom-research.md`

**2. The core pain is tool-output bloat in the live context**
- *Confidence: Single-source*
- "MCP tool outputs are the PERFECT use case for Headroom. They're often large (100s-1000s of items), structured (JSON)" — `headroom-research.md` (from MCP module docstring)

**3. Claimed savings are 60–95% on real agent workloads with benchmarked accuracy preservation**
- *Confidence: Single-source (vendor benchmarks, not reproduced here)*
- "Code search (100 results) … 17,765 → 1,408 … **92%**" — `headroom-research.md`
- "GSM8K … Baseline 0.870 | Headroom 0.870 | **±0.000**" — `headroom-research.md`

**4. Reversibility via CCR is a first-class design constraint**
- *Confidence: Single-source*
- "Unlike traditional lossy compression, CCR guarantees that every piece of original data remains accessible" — `headroom-research.md`

### Gaps

- No reproduction of benchmark numbers in this corpus.
- No user interviews on whether CCR retrieval actually fires in production agents.
- No measurement of latency impact at TeamShared-scale recall payloads.
- Unknown false-negative rate (critical detail lost, model never retrieves).

### Discovery questions

1. When your agent missed a critical log line, was it compression, retrieval, or bad recall?
2. Do you run a local proxy in front of your agent, or compress in-application?
3. What is the acceptable p99 latency add per tool call for 80% token savings?

---

## discovery-query #2: How does Headroom relate to TeamShared?

> Corpus health: **thin**. Cross-product comparison is analyst synthesis grounded
> in single-source Headroom docs + internal TeamShared intent (multi-source for
> TeamShared features only).

### Findings

**1. Orthogonal layers — compression vs persistence**
- *Confidence: Single-source (analyst note in source)*
- "Headroom: shrinks the *current prompt* … TeamShared: persists *durable* semantic/episodic/procedural memory" — `headroom-research.md`

**2. Headroom's MCP tools compress tool results; TeamShared MCP tools produce them**
- *Confidence: Single-source*
- MCP tools: `headroom_compress`, `headroom_retrieve`, `headroom_stats` — `headroom-research.md`
- TeamShared: `memory_recall`, `memory_remember`, five pillars — internal docs (prior graph)

**3. Both ship `headroom learn` / distillation-adjacent features, but different outputs**
- *Confidence: Single-source*
- "`headroom learn` — mines failed sessions, writes corrections to `CLAUDE.md` / `AGENTS.md`" — `headroom-research.md`
- TeamShared: distiller + curator → `wiki_pages`, episodic events — internal docs

**4. Headroom has 41k GitHub stars — distribution in the compression category, not memory**
- *Confidence: Single-source*
- "~41k GitHub stars" — `headroom-research.md`

**5. Explicit integration pattern exists in Headroom docs**
- *Confidence: Single-source*
- "TeamShared MCP tool results and `memory_recall` hits could pass through Headroom compression before entering agent context" — `headroom-research.md` (analyst note)

### Gaps

- No evidence anyone runs TeamShared + Headroom together.
- Tension unresolved: TeamShared promises citation fidelity; Headroom compresses citations away unless CCR retrieves.
- Headroom memory module vs TeamShared pillars — overlap unclear, no comparison in corpus.

### Discovery questions

1. Would you want recall hits compressed before the agent reads them, or full-fidelity with token cost?
2. Does your team separate "context optimization budget" from "memory infrastructure budget"?
3. If Headroom wrapped your Cursor agent, would TeamShared MCP still add value?

---

## discovery-query #3: What is Headroom's technical moat?

### Findings

**1. Content-type-aware routing with six specialized compressors**
- *Confidence: Single-source*
- ContentRouter routes to SmartCrusher, CodeCompressor, Kompress, LogCompressor, SearchCompressor, DiffCompressor — `headroom-research.md`

**2. CCR reversibility + TOIN learning loop**
- *Confidence: Single-source*
- CCR: hash-indexed SQLite retrieve — `headroom-research.md`
- TOIN: per-tool learned compression patterns — `headroom-research.md`

**3. CacheAligner + provider cache hints = stacked savings**
- *Confidence: Single-source*
- "SmartCrusher reduces token count … CacheAligner makes repeated calls cheaper on cached prefix tokens" — this doc §3–4

**4. Agent-wrap distribution (`headroom wrap cursor`) lowers adoption friction**
- *Confidence: Single-source*
- "Cursor ✅ prints config — paste once" — `headroom-research.md`

**5. Kompress-base is a custom HF model trained on agentic traces**
- *Confidence: Single-source*
- "kompress-base — our HuggingFace model, trained on agentic traces" — `headroom-research.md`

### Gaps

- SmartCrusher statistical methods are documented but not independently audited.
- Rust/Python split and ONNX dependency create corporate-network install friction (documented in README).
- RTK and lean-ctx ship overlapping CLI compression; Headroom bundles RTK — moat vs partners unclear.

---

## Head-to-head: Headroom vs TeamShared

| Dimension | Headroom | TeamShared | Relationship |
|---|---|---|---|
| **Category** | Context compression / token optimization | Durable multi-pillar org brain | Complementary |
| **When it runs** | Per LLM request (pre-send) | Write anytime; read on recall | Different lifecycle |
| **Primary artifact** | Compressed messages + CCR hashes | Memories, episodes, skills, wiki | Different |
| **Multi-tenant** | No (local/proxy per machine) | Yes (RLS, orgs, RBAC) | TeamShared only |
| **MCP role** | Compress/retrieve tool *outputs* | Remember/recall/think *knowledge* | Stackable |
| **Reversibility** | CCR within TTL | Full record + soft-delete | Both |
| **Learning loop** | TOIN + headroom learn → AGENTS.md | Distiller + curator → wiki | Overlap on rules, not facts |
| **Distribution** | 41k★, PyPI, npm, Docker | teamshared.com, Cursor plugin | Headroom leads awareness |
| **Benchmarks** | GSM8K, SQuAD, BFCL published | Integration tests, smoke scripts | Headroom leads rigor |
| **License** | Apache 2.0 | (teamshared) | Both open |

---

## tradeoff-frame: Should TeamShared integrate Headroom-style compression?

### The decision

Should TeamShared add an upstream context-compression layer (integrate Headroom
or build equivalent) for MCP tool results and recall payloads?

**Options:**
- **A.** Integrate Headroom (proxy or library) as documented optional layer
- **B.** Build native compression in TeamShared server (SmartCrusher-style for recall hits)
- **C.** Stay full-fidelity; let agents/clients bring their own compression

### Real axes

1. **Citation fidelity vs token cost** — recall promises grounded citations; compression hides detail until CCR retrieve
2. **Server-side vs client-side** — who owns the compression boundary
3. **Complexity budget** — ONNX/Rust/proxy ops vs Python Mem0 stack
4. **Category positioning** — "memory brain" vs "memory + context optimization platform"
5. **Time to value** — Headroom ships today; native build is quarters

### Option profiles

**A — Integrate Headroom**
- Optimizes: fastest path to 60–90% token reduction on fat tool outputs; leverages 41k★ ecosystem; Apache 2.0
- Sacrifices: external dependency; corporate TLS/Rust install friction; two systems to debug; citation UX complexity

**B — Build native**
- Optimizes: single product surface; compression tuned to TeamShared record shapes; no proxy hop
- Sacrifices: engineering time; unlikely to match six compressors + Kompress model quickly; benchmark burden

**C — Stay full-fidelity**
- Optimizes: simplest story ("we never hide your memories"); curator/wiki already summarize for humans
- Sacrifices: agents pay full token cost on every `memory_recall`; context rot pain unaddressed at MCP layer

### Reversibility

**Two-way door** for Option A (optional plugin/proxy, remove if bad).
**One-way door** for Option B if native compression shapes API contracts.
Option C preserves status quo — fully reversible.

### Decisive evidence

- Measure: token count of typical `memory_recall(k=8)` payload vs SmartCrusher-compressed equivalent; did the agent answer correctly on a held-out task set?
- User signal: do teams hit context limits *because of recall*, or because of tool output?
- Operational: can TeamShared server run ONNX/Kompress in Docker compose without breaking Spark/Linux deploys?

Frame the decision. Then make the call yourself, or escalate to whoever owns it.

---

## Recommended product responses (not mogkit output — engineering judgment)

1. **Document the layering** — TeamShared = durable brain; Headroom = optional
   context shrink-wrap. No competitive panic.
2. **Spike integration** — `headroom wrap cursor` in front of TeamShared MCP;
   measure tokens on `memory_recall` + capture middleware payloads.
3. **Add to landscape graph** — Headroom is a **adjacent tool**, not a 15th
   memory competitor; tag as `context-compression` in future graphify passes.
4. **Watch headroom learn** — overlaps with skills/playbooks thesis; if it
   gains traction, TeamShared's manual `memory_skill_set` loop looks slower.
5. **Do not compress by default** until CCR + citation UX is proven — TeamShared's
   brand is grounded recall, not lossy summaries.

---

## Next mogkit steps

1. Re-run `graphify` to ingest `headroom-research.md` into `product/graph/graph.json`.
2. `discovery-query`: "Does context rot from recall payloads block TeamShared adoption?"
3. `spec-stress-test`: red-team a Headroom-wrapped TeamShared MCP install path.
