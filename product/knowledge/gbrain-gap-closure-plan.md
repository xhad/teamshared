# GBrain gap-closure plan

Roadmap to close the **feature gaps** identified in
`product/knowledge/gbrain-competitor-analysis.md` without abandoning TeamShared's
differentiators (consent-first capture, managed multi-tenant governance, work/
strategic/approval pillars).

**Out of scope (intentional forks, not gaps):**
- Aggressive signal-detector ingestion on every message
- Git-repo-as-system-of-record (markdown brain repo + sync)
- Matching GBrain's 23k-star distribution (separate GTM track)

**Current baseline (already shipped):**
- Hybrid vector + keyword merge in `SecureRetrieval` (`retrieval.py`) — but merge is naive `_merge_by_id`, no RRF
- `memory_assemble_context` — cited context pack, not synthesized answer
- Distiller + curator workers — session/subject enrichment, not scheduled dream cycle
- Graph via optional Neo4j — manual `memory_graph_relate` only, no autolink on write
- Skills + procedural playbooks — converging with GBrain skillpack

---

## Phase 1 — `memory_think` (synthesis + gap analysis)

**Goal:** Match GBrain's `gbrain think` — one MCP call returns a synthesized,
cited answer plus explicit gaps (stale, missing, contradictory).

**Why first:** Biggest UX gap in competitive matrix; builds on existing retrieval.

| # | Task | Owner layer | Notes |
|---|---|---|---|
| 1.1 | Define `ThinkResult` type (`answer_md`, `citations[]`, `gaps[]`, `sources_used`, `tokens`) | `memory/types.py` | `gaps` entries: `kind` (stale \| missing \| contradicts \| low_confidence), `claim`, `evidence` |
| 1.2 | Add `Thinker` module: recall → pack → LLM compose → parse structured output | `memory/think.py` or `distill/thinker.py` | Reuse `SecureRetrieval.search` + `ContextAssembler.pack_records`; new prompt in `distill/prompts.py` |
| 1.3 | Gap heuristics (no extra LLM): stale if newest source > N days; missing if query entities have no memory; contradicts if recall surfaces conflicting facts | `memory/think.py` | Start rule-based; optional LLM judge later (GBrain `suspected-contradictions`) |
| 1.4 | `MemoryFacade.think()` — permission path identical to `recall` | `memory/facade.py` | Audit as `memory.think` |
| 1.5 | MCP tool `memory_think` (+ alias `memory_search` for raw recall if we want parity) | `server/tools.py`, `tool_catalog.py` | Params: `query`, `k`, `repo`, `github`, `max_tokens` |
| 1.6 | Extend `memory_assemble_context` with optional `synthesize=true` **or** keep separate tools | decision | Prefer **separate** `memory_think` — clear `search` vs `think` split like GBrain |
| 1.7 | Console: "Ask the brain" box on `/app/memory` calling think endpoint | `server/console.py` | Human-visible proof of synthesis |
| 1.8 | Tests: mock LLM, fixture corpus, assert citations reference real `memory_id`s | `tests/test_think.py` | Pin prompt contract |
| 1.9 | README + plugin rule: when to `memory_recall` vs `memory_think` | docs | Agent protocol update |

**Exit criteria:** Agent can ask "what do I need to know before meeting X?" and get prose + citations + "heads up: nothing since DATE" gap block.

**Depends on:** nothing (uses existing retrieval).

**Estimate:** 1–2 weeks.

---

## Phase 2 — Graph autolink on write (zero LLM)

**Goal:** Every `memory_remember` / ingestion write extracts entity refs and creates
typed edges automatically — GBrain's +31 P@5 graph lift without LLM cost.

| # | Task | Owner layer | Notes |
|---|---|---|---|
| 2.1 | `extract_entity_refs(content) -> list[EntityRef]` — `[[subject]]`, `@entity`, markdown links, `subject:` frontmatter | `memory/autolink.py` | Pure regex; no LLM |
| 2.2 | Predicate inference table: `person`+`company` → `works_at`; co-occurrence → `mentions`; tags `repo:` → `works_on` | `memory/autolink.py` | Start with 5–8 predicates; extensible |
| 2.3 | Hook `IngestionPipeline` post-write: call autolink → `graph.add_relation` | `ingestion/pipeline.py` | Feature-flag `TEAMSHARED_AUTOLINK_ENABLED` |
| 2.4 | **Postgres fallback graph** when Neo4j disabled — `memory_graph_edges` table + traversal in `GraphStore` interface | migration + `memory/graph_pg.py` | GBrain wins even without Neo4j; we shouldn't require optional extra |
| 2.5 | Entity stub memories: first mention of unknown entity creates low-weight semantic stub | `ingestion/pipeline.py` | Optional; GBrain grows graph this way |
| 2.6 | Retrieval boost: neighbors of top recall hits get adjacency bonus in `_rerank` | `memory/retrieval.py` | GBrain "graph signals" — start 1-hop |
| 2.7 | Tests: write memory with `[[alice]]` → edge exists; recall query boosts linked records | `tests/test_autolink.py` | Zero LLM mocks |
| 2.8 | `memory_recall` records include `evidence` tag (matched_vector \| matched_keyword \| graph_neighbor) | `memory/types.py` | GBrain `--explain` parity |

**Exit criteria:** Writing "Alice works at Acme" auto-creates `alice → works_at → acme`; query "who works at Acme?" surfaces Alice via graph boost.

**Depends on:** Phase 2.4 before 2.6 if Neo4j optional in prod.

**Estimate:** 2 weeks.

---

## Phase 3 — Retrieval quality + eval CI

**Goal:** Credible benchmarks and hybrid ranking — close GBrain's eval moat.

| # | Task | Owner layer | Notes |
|---|---|---|---|
| 3.1 | Replace `_merge_by_id` with **RRF** (reciprocal rank fusion) for vector + keyword lists | `memory/retrieval.py` | k=60 standard; per-pillar pools |
| 3.2 | Best-chunk-per-memory pooling in vector search (DISTINCT ON already partial) | `vectorstore.py` | Ensure one memory surfaces on strongest chunk |
| 3.3 | Title/subject/alias boost — `subject` exact match, tag `github:` / `repo:` soft boost (exists in facade recall) | `facade.py` `_rerank` | Align with GBrain title-phrase boost |
| 3.4 | Optional reranker stage — pluggable `Reranker` (start: lightweight cross-encoder or skip for v1) | `memory/rerank.py` | Env `TEAMSHARED_RERANKER=none\|...` |
| 3.5 | `memory_recall_explain` or `explain=true` param — per-record score attribution | `facade.recall` | vector score, keyword rank, RRF, graph boost, pillar weight |
| 3.6 | **NamedThingBench fixture** — 20–50 synthetic org memories, queries that name entities | `tests/eval/named_thing_bench.json` + `tests/test_retrieval_eval.py` | Hard-gate P@5 on CI |
| 3.7 | **Replay harness** — export real `memory_recall` queries from audit log → replay after changes | `scripts/eval_replay.py` | GBrain `eval export` / `eval replay` |
| 3.8 | Dashboard metric: retrieval eval score on `/memory` status page | `server/dashboard.py` | Public credibility |
| 3.9 | Document methodology in `docs/eval/retrieval.md` | docs | Match GBrain's eval transparency |

**Exit criteria:** CI fails if NamedThingBench P@5 drops >5pts; `explain=true` shows why each record ranked.

**Depends on:** Phase 2.6 for graph boost in eval.

**Estimate:** 2–3 weeks.

---

## Phase 4 — Dream cycle (scheduled maintenance)

**Goal:** Overnight enrichment loop — GBrain's cron jobs without abandoning consent.

| # | Task | Owner layer | Notes |
|---|---|---|---|
| 4.1 | Define dream job types: `stale_scan`, `dedup_subjects`, `contradiction_sample`, `curator_sweep`, `salience_score` | `memory/dream.py` | Only operates on **already-ingested** memory |
| 4.2 | Redis queue `working:dream:queue` + `DreamWorker` process | `distill/dream_worker.py` | Compose service in `docker-compose.yml` |
| 4.3 | Org-level cron config (console or `teamshared dream schedule`) | CLI + `/app` | Default: nightly 3am UTC per org |
| 4.4 | `stale_scan` — flag memories with no corroboration past threshold; write episodic "staleness" notes | dream job | Feeds `memory_think` gaps |
| 4.5 | `contradiction_sample` — paired retrieval + lightweight LLM judge (optional, cost-capped) | dream job | GBrain `suspected-contradictions` |
| 4.6 | `curator_sweep` — enqueue dirty subjects not yet wiki-curated | reuses `curator_worker` | |
| 4.7 | MCP `memory_dream_status` — last run, jobs completed, findings count | `server/tools.py` | Operator visibility |
| 4.8 | Tests: dream job idempotency, consent boundary (no new external ingest) | `tests/test_dream_worker.py` | |

**Exit criteria:** Nightly worker runs per org; `memory_think` gap block includes dream-cycle staleness/contradiction flags.

**Depends on:** Phase 1 (gaps), existing curator.

**Estimate:** 2 weeks.

---

## Phase 5 — Entity typing (light schema packs)

**Goal:** Structured memory shape without full GBrain schema-pack machinery.

| # | Task | Owner layer | Notes |
|---|---|---|---|
| 5.1 | Extend `MemoryKind` with org-configurable kinds: `person`, `company`, `project`, `deal` | `types.py` + migration | Or use `subject` + `tags:type-person` convention first |
| 5.2 | `memory_entity_get(name)` — rollup of semantic facts + graph neighbors + wiki page | `facade.py` | GBrain page lookup parity |
| 5.3 | Ingestion: infer kind from `subject` prefix or tag | `ingestion/pipeline.py` | |
| 5.4 | Console entity pages in wiki (`/app/wiki/topic/{slug}`) — already partial | `console.py` | Wire entity_get into topic view |
| 5.5 | Defer full `schema_pack` authoring until design partners ask | — | YAGNI unless eval proves need |

**Depends on:** Phase 2 (graph), Phase 1 (think on entity queries).

**Estimate:** 1–2 weeks (minimal); 4+ weeks (full schema packs).

---

## Phase 6 — Distribution parity (agent-install)

**Goal:** Reduce GBrain's install friction advantage for OpenClaw/Hermes/Cursor.

| # | Task | Owner layer | Notes |
|---|---|---|---|
| 6.1 | `INSTALL_FOR_AGENTS.md` at repo root — agent-readable 9-step protocol | docs | Mirror GBrain pattern; point at `install.sh` |
| 6.2 | `teamshared doctor` — health + embedder mismatch + graph coverage | `cli.py` | GBrain `gbrain doctor` parity |
| 6.3 | `teamshared connect <url> --token --install` for remote MCP wiring | `cli.py` | Claude/Codex/Cursor snippets |
| 6.4 | Plugin: ship INSTALL doc in install page + agent harness test | `plugins/teamshared/` | |
| 6.5 | Smoke: `scripts/smoke_all_tools.py` adds `memory_think` step | scripts | |

**Depends on:** Phase 1 for think in smoke.

**Estimate:** 1 week.

---

## Suggested execution order

```
Phase 1 (think) ──────────────────────────────► ship first, demo-ready
        │
        ├──► Phase 6 (install docs) — parallel once think lands
        │
Phase 2 (autolink) ──► Phase 3 (eval/RRF) ──► Phase 4 (dream cycle)
        │
        └──► Phase 5 (entity typing) — when 2+3 stable
```

**MVP to claim GBrain parity in demos (4–6 weeks):** Phase 1 + Phase 2 + Phase 3.1–3.6 + Phase 6.1.

---

## Success metrics

| Metric | Baseline | Target |
|---|---|---|
| NamedThingBench P@5 (synthetic) | unmeasured | ≥ 0.40 (beat vector-only by ≥15pts) |
| `memory_think` gap block present | 0% | 100% of think responses with ≥1 gap or explicit "no gaps" |
| Autolink edges per 100 writes | 0 | ≥ 20 entity refs extracted |
| Dream cycle coverage | none | nightly per active org |
| Agent install time (doctor green → first think) | unknown | < 30 min documented path |

---

## Work items (for `work_*` queue)

| Title | Phase | Priority |
|---|---|---|
| Implement `memory_think` synthesis + gap analysis | 1 | P0 |
| Graph autolink on ingestion write (zero LLM) | 2 | P0 |
| RRF hybrid merge + retrieval explain mode | 3 | P0 |
| NamedThingBench eval fixture + CI gate | 3 | P0 |
| Dream cycle worker (stale + curator sweep) | 4 | P1 |
| Postgres graph fallback when Neo4j disabled | 2 | P1 |
| `INSTALL_FOR_AGENTS.md` + doctor command | 6 | P1 |
| Entity rollup `memory_entity_get` | 5 | P2 |
| Contradiction sampling dream job | 4 | P2 |
| Optional reranker provider | 3 | P2 |

---

## Key files to touch (by phase)

| Phase | Primary paths |
|---|---|
| 1 | `src/teamshared/memory/think.py`, `distill/prompts.py`, `memory/facade.py`, `server/tools.py` |
| 2 | `memory/autolink.py`, `ingestion/pipeline.py`, `memory/graph.py`, `infra/migrations/025_graph_edges.sql` |
| 3 | `memory/retrieval.py`, `memory/vectorstore.py`, `tests/eval/`, `scripts/eval_replay.py` |
| 4 | `distill/dream_worker.py`, `memory/working.py` (queue), `infra/docker-compose.yml` |
| 5 | `memory/types.py`, `memory/facade.py`, `server/console.py` |
| 6 | `INSTALL_FOR_AGENTS.md`, `src/teamshared/cli.py`, `plugins/teamshared/` |

Frame the decision: **ship think first** — it's the feature buyers will feel vs GBrain on day one. Autolink + eval CI make it defensible; dream cycle makes it compound.
