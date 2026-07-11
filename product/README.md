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
│                 currently: symlinks to the repo's internal planning docs
├── engine/
│   └── graph-schema.json   the contract graphify output must satisfy
├── graph/
│   ├── graph.json          the evidence graph (schema-valid, provenance on every node/edge)
│   └── graph.md            human-readable summary + health banner
├── knowledge/
│   └── assumption-audit.md the 8 load-bearing bets ranked by decision-at-risk
└── README.md
```

## Current state

The graph was built from **internal product intent** (`prod-plan.md`,
`plan.md`, `memory-wiki-plan.md`, plus `README.md`/`AGENTS.md`) and **external
signals** (`company-brain-yc-rfs.md`, `gbrain-competitor-research.md`,
`shared-brain-landscape-2026.md`, `palantir-foundry-ontology-research.md`,
`headroom-research.md`, `screenpipe-research.md`, `mex-research.md`,
`cognee-research.md`). Corpus health is still **thin** — there is no captured
user research yet. The headline finding: the plan is detailed, but the core bets
have **zero user evidence**. GBrain and Cognee are the primary Tier-1 memory
competitors (`knowledge/gbrain-competitor-analysis.md`,
`knowledge/cognee-competitor-analysis.md` — graph+vector platform ~27.5k stars,
MCP + Cognee Cloud); Headroom is
the main **adjacent** context-compression layer (`knowledge/headroom-architecture-analysis.md`
— orthogonal to TeamShared, not a brain replacement); Screenpipe is the main
**adjacent** ambient desktop capture layer (`knowledge/screenpipe-competitor-analysis.md`
— local screen+audio memory + MCP, not a multi-tenant org brain); Palantir Foundry
ontology is the architectural reference for a governed entity/action layer
(`knowledge/palantir-ontology-analysis.md`); mex is the main **adjacent** repo-scoped
markdown scaffold + drift CLI (`knowledge/mex-competitor-analysis.md` — git-local
ROUTER/patterns, not a multi-tenant org brain). See `knowledge/assumption-audit.md`.

## How to move it forward

1. **Run the design-partner cycle.** Use
   `knowledge/design-partner-runbook.md` and copy
   `sources/interview-template.md` for each anonymized interview.
2. **Add real research.** Drop interview transcripts, support tickets, or sales
   call notes into `sources/` (with `type:` frontmatter). Re-run `graphify`.
3. **Discovery wedge** (graph-based): `graphify` → `assumption-audit` →
   `discovery-query` → `interview-guide` → `synthesis-map` → `prd-interrogate`.
4. **Standalone skills** (no graph needed) that fit TeamShared right now:
   - `metrics-tree` — TeamShared has no measurable outcome; give it one.
   - `narrative-review` — pressure-test `prod-plan.md` as an exec would.
   - `spec-stress-test` — red-team the capture/ingestion spec.
   - `tradeoff-frame` — frame shared-by-default vs isolated-by-default honestly.

Run a playbook by fetching it from teamshared: `memory_procedure_get(name="graphify")`.
