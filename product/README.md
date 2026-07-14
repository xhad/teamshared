# product/ — TeamShared product planning (mogkit workspace)

A [mogkit](https://github.com/Waddling-Penguin/mogkit) PM workspace for planning
**TeamShared**. mogkit is a collection of product playbooks (stored in teamshared
under the `mogkit` tag) that turn raw research into an evidence graph and then
interrogate it — surfacing what's actually supported, what's assumed, and what to
validate next. The playbooks never write the PRD for you; they make *your*
thinking sharper.

## Layout

```
product/
├── sources/      raw research (one file per artifact); graphify reads these
│                 symlinks to README.md, AGENTS.md, PRODUCT.md, prod-plan.md
├── engine/
│   └── graph-schema.json   the contract graphify output must satisfy
├── graph/
│   ├── graph.json          the evidence graph (schema-valid, provenance on every node/edge)
│   └── graph.md            human-readable summary + health banner
├── knowledge/
│   └── assumption-audit.md the load-bearing bets ranked by decision-at-risk
└── README.md
```

## Current state (2026-07-12)

**Canonical shipped description:** `sources/shipped-state-2026-07-12.md` — what the
codebase actually ships today (six memory pillars, context compression, work/projects,
ontology console, OTP multi-tenant console, curator/distiller workers). Use this
as the source of truth for product messaging; `prod-plan.md` remains roadmap.

The graph was last built from **20 sources**: six internal docs (including shipped
state, README, AGENTS, PRODUCT) plus eleven external research artifacts (YC RFS,
GBrain, shared-brain-landscape-2026, Headroom, Screenpipe, mex, OpenClaw memory,
Palantir ontology, Cognee, RACT, PromptQL). Corpus health is **developing** — there is still **no
captured user research** (interviews, tickets, support threads).

**Graph stats:** 185 nodes · 113 edges · 19 assumptions surfaced.

**Headline finding:** The product is substantially built (clean-room engineering
baseline passed 2026-07-11), but the core bets still have **zero user evidence**.
GBrain and Cognee are the primary Tier-1 memory competitors; TeamShared's shipped
differentiation is governance + team workflow (work queue, OKRs, curated wiki,
ontology, context compression) — not graph depth alone. See
`knowledge/assumption-audit.md` and `graph/graph.md`.

**Competitor analyses** (mogkit `discovery-query` + `tradeoff-frame`):

| Adjacent / Tier-1 | Knowledge doc |
|---|---|
| GBrain | `knowledge/gbrain-competitor-analysis.md` |
| Cognee | `knowledge/cognee-competitor-analysis.md` |
| Headroom (compression) | `knowledge/headroom-architecture-analysis.md` |
| Screenpipe (desktop capture) | `knowledge/screenpipe-competitor-analysis.md` |
| mex (repo scaffold) | `knowledge/mex-competitor-analysis.md` |
| OpenClaw native memory (harness file memory) | `knowledge/openclaw-memory-analysis.md` |
| PromptQL (multiplayer AI + shared wiki) | `knowledge/promptql-competitor-analysis.md` |
| RACT (coding harness) | `knowledge/ract-competitor-analysis.md` |
| Palantir ontology (reference) | `knowledge/palantir-ontology-analysis.md` |
| Landscape | `knowledge/shared-brain-landscape-analysis.md` |

## How to move it forward

1. **Run the design-partner cycle.** Use
   `knowledge/design-partner-runbook.md` and copy
   `sources/interview-template.md` for each anonymized interview.
2. **Add real research.** Drop interview transcripts, support tickets, or sales
   call notes into `sources/` (with `type:` frontmatter). Re-run `graphify`.
3. **Discovery wedge** (graph-based): `graphify` → `assumption-audit` →
   `discovery-query` → `interview-guide` → `synthesis-map` → `prd-interrogate`.
4. **Standalone skills** (no graph needed) that fit TeamShared right now:
   - `metrics-tree` — TeamShared has no measurable outcome; give it one (`knowledge/metrics-tree.md`).
   - `narrative-review` — pressure-test `prod-plan.md` as an exec would (`knowledge/narrative-review.md`).
   - `spec-stress-test` — red-team the capture/ingestion spec.
   - `tradeoff-frame` — frame shared-by-default vs isolated-by-default honestly.

Run a playbook by fetching it from teamshared: `memory_skill_get(name="graphify")`.

## Syncing product docs with the codebase

When shipping significant features, update `sources/shipped-state-2026-07-12.md`
(or add a dated successor), then re-run `graphify` so the evidence graph and
`graph.md` health banner stay aligned with reality. The public landing page lives
in `src/teamshared/server/token_api.py` (`_landing_page_html`) — keep it in sync
with shipped-state.
