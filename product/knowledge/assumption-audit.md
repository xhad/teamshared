# Assumption audit — TeamShared

Generated via mogkit `assumption-audit` on `product/graph/graph.json` (2026-07-11
graphify pass: 13 sources, 131 nodes, health **developing**).

## Health context

Corpus health is **developing**: 13 sources across `research`, `prd`, `memo`, and
`doc` types — five internal product-intent docs plus eight external research
artifacts (GBrain, **Cognee**, shared-brain-landscape, Headroom, Screenpipe, mex,
Palantir ontology, YC RFS). There is still **zero user-research evidence** (no
interviews, tickets, or support threads). External research is vendor/analyst
intelligence, not buyer validation — single-source is still the norm for
competitive claims. Totals: **13 assumptions** (zero provenance) and **101
single-source nodes** (one provenance entry each); only **17 nodes** have
multi-source backing.

On a developing-but-not-rich corpus, the High bar is calibrated to **decisions at
stake**, not evidence-thinness alone.

---

## Assumptions (zero provenance)

Ranked High → Medium → Low. Every Assumption node from the graph is listed.

### High

1. **Teams actually want cross-agent shared memory.**
   - Decision at risk: the entire roadmap — multi-tenancy, scopes, connectors,
     enterprise, capture — assumes the shared-brain thesis is wanted.
   - Source of assumption: voiced internally (`prod-plan.md`: "proof of concept for
     shared agent memory" → production with no demand evidence between).

2. **Orgs will pay for 'shared agent context' as infrastructure.**
   - Decision at risk: whether there is a business; pricing and GTM.
   - Source of assumption: `prod-plan.md` names "multi-tenant organization
     customers" without a quoted buyer or WTP signal. GBrain is MIT; Cognee ships
     managed cloud; Mem0/Zep/Letta monetize cloud tiers.

3. **Default cross-agent visibility (the "shared brain") is what users want.**
   - Decision at risk: core read-path default (`memory_recall` unscoped by default).
     If buyers expect isolation-by-default (GBrain per-login slices, Cognee per-
     dataset ACL), the headline feature becomes a trust liability.
   - Source of assumption: `prod-plan.md` "Shared memories across teams and agents"
     — no user on record preferring shared-by-default.

4. **LLM distillation yields durable, low-noise memory worth recalling.**
   - Decision at risk: recall quality — the product's value layer. If distilled
     memory is noisy or wrong, every pillar sits on bad data.
   - Source of assumption: `memory-wiki-plan.md` distiller/curator design with no
     quality measurement. GBrain eval CI and Cognee `improve` loop set a higher
     external bar.

5. **TeamShared governance (work queue, OKRs, approvals, capture) differentiates
   vs Cognee without graph parity.**
   - Decision at risk: post-Cognee positioning — whether to invest in graph
     ontology/recall routing (Cognee's moat) or double down on org ops (work,
     strategic, approvals, server-side capture). If buyers pick on ~27.5k stars
     and graph depth alone, governance is irrelevant.
   - Source of assumption: inferred from `cognee-competitor-analysis.md` tradeoff-
     frame; Cognee docs surface no `work_*` / OKR / approval equivalents.

### Medium

6. **GBrain or Cognee is the primary direct competitor (not the broader field).**
   - Decision at risk: competitive positioning, demo narrative, roadmap sequencing.
     Hivemind auto-skill-mines; Mem0/Zep/Letta have larger adoption; mex/Headroom
     are adjacent. Narrowing to GBrain+Cognee may miss the buyer's actual shortlist.
   - Source of assumption: competitive analysis synthesis — not validated by buyer
     eval criteria.

7. **Synthesis + gap analysis is required to win (not just hybrid recall).**
   - Decision at risk: quarters of engineering on `memory_think` / gap UX vs
     governance/console investment. GBrain `think` leads here; Cognee `recall`
     auto-routes graph completion without documented gap analysis.
   - Source of assumption: GBrain research + internal gap vs `memory_recall`
     returning records.

8. **Bi-temporal fact validity is not needed for TeamShared's buyer.**
   - Decision at risk: whether to invest in Graphiti-style `valid_from` /
     `invalid_at` vs timestamp-only facts + curator rewrites.
   - Source of assumption: absence of buyer signal; Graphiti/Zep LongMemEval claims
     are disputed but directionally threatening.

9. **Explicit `memory_skill_set` is enough; an auto-trace-to-skill miner is not
   needed.**
   - Decision at risk: skills pillar roadmap. Hivemind mines traces into SKILL.md
     automatically and pitches it as headline differentiator.
   - Source of assumption: internal product shape vs Hivemind vendor claims.

10. **TeamShared doesn't need a published benchmark number to compete.**
    - Decision at risk: credibility in competitive evals. Mem0 (ECAI 2025), Zep
      (71% LongMemEval, disputed), GBrain (NamedThingBench CI) all publish numbers.
    - Source of assumption: strategic KPI "reliable enough to trust" is asserted,
      not measured.

11. **SSO/SAML/SOC2 gate the deals worth chasing.**
    - Decision at risk: Phase 3 enterprise sequencing — built too early or too late.
    - Source of assumption: `prod-plan.md` "Enterprise security baseline". GBrain
      and Cognee both target OAuth/dataset-permission teams first.

12. **Humans will actually browse the memory wiki/console.**
    - Decision at risk: console + curator + wiki phase — large UI investment.
    - Source of assumption: `memory-wiki-plan.md`. GBrain and Cognee optimize
      agent-query over human browsing.

### Low

13. **Slack/GitHub/Notion/etc. connectors are the adoption lever.**
    - Decision at risk: connector roadmap ordering — recoverable once usage exists.
    - Source of assumption: `plan.md` connector list. GBrain already ingests
      meetings/email/voice via recipes; table stakes, not differentiation.

---

## Single-source claims (one provenance entry)

Load-bearing claims only — not all 101 single-source nodes. Ranked High → Medium → Low.

### High

- **"Context rot" is the pain TeamShared solves.**
  - Decision at risk: problem framing in positioning and plugin rule.
  - Single source: `plan.md` (industry landscape paragraph, not a TeamShared user).
  - Triangulate with: one design-partner interview describing losing agent context
    across sessions.

- **No cross-tenant leakage "by design".**
  - Decision at risk: production-ready security outcome; one-way-door claim.
  - Single source: `plan.md` principle.
  - Triangulate with: security review / pen-test, not stated principle alone.

- **Cognee is Tier-1 direct memory competitor (not adjacent).**
  - Decision at risk: competitive map, MCP boot guidance, resource allocation vs
    mex/Headroom.
  - Single source: `cognee-research.md` (vendor docs — no buyer eval).
  - Triangulate with: design-partner shortlist ("did you evaluate Cognee?").

- **Synthesized answers with gap analysis are a buyer requirement.**
  - Decision at risk: `memory_think` investment priority.
  - Single source: `gbrain-competitor-research.md` ("The gap analysis is the
    differentiator").
  - Triangulate with: buyer walk-through of last memory miss — retrieval vs
    synthesis vs permissions failure.

- **GBrain has distribution lead (23k stars, YC CEO, OpenClaw native).**
  - Decision at risk: whether to chase OpenClaw/Hermes install parity.
  - Single source: `gbrain-competitor-research.md`.
  - Triangulate with: harness adoption data from design partners; Cognee also
    ships OpenClaw plugin (~27.5k stars).

### Medium

- **Cognee and GBrain are comparable OSS scale peers (~27k vs ~23k stars).**
  - Decision at risk: treating Cognee as "also ran" vs co-equal Tier-1 threat.
  - Single source: `cognee-research.md`.
  - Triangulate with: independent star/adoption tracking + buyer mention frequency.

- **Cognee managed cloud GTM is closer to TeamShared than GBrain OSS-only.**
  - Decision at risk: SaaS positioning and pricing narrative.
  - Single source: `cognee-research.md`.
  - Triangulate with: Cognee Cloud pricing page + buyer WTP interviews.

- **MCP is the de facto "USB-C for memory" standard.**
  - Decision at risk: MCP-first GTM vs REST/console-first.
  - Single source: `shared-brain-landscape-2026.md`.
  - Triangulate with: design-partner harness inventory (how many run dual MCP?).

- **YC RFS validates "company brain" as a venture category.**
  - Decision at risk: category timing and investor narrative.
  - Single source: `company-brain-yc-rfs.md` (Tom Blomfield vision, not buyer demand).
  - Triangulate with: funded competitors' revenue/traction, not RFS alone.

- **Headroom is orthogonal (compression, not durable brain).**
  - Decision at risk: whether to integrate/bundle vs ignore.
  - Single source: `headroom-research.md`.
  - Triangulate with: user running Headroom + memory MCP together.

- **Screenpipe is orthogonal (ambient capture, not org brain).**
  - Decision at risk: capture strategy vs server-side middleware.
  - Single source: `screenpipe-research.md`.
  - Triangulate with: trust/privacy interview on ambient vs explicit capture.

- **mex is Tier-3 repo-scaffold adjacent; complements TeamShared on repo hygiene.**
  - Decision at risk: dual-MCP boot guidance vs building drift detection in-plugin.
  - Single source: `mex-research.md`.
  - Triangulate with: design partners running mex alongside TeamShared.

- **Palantir ontology is architectural reference, not memory competitor.**
  - Decision at risk: ontology/action-type roadmap sequencing.
  - Single source: `palantir-foundry-ontology-research.md`.
  - Triangulate with: internal entity-hub usage before governed actions.

- **The 2026 landscape: no system wins on >3 of 8 dimensions.**
  - Decision at risk: which axis TeamShared commits to winning.
  - Single source: `shared-brain-landscape-2026.md`.
  - Triangulate with: buyer-ranked feature checklist (not analyst synthesis).

- **Zep vs Mem0 LongMemEval numbers are methodologically disputed.**
  - Decision at risk: whether to cite competitor benchmarks at all.
  - Single source: `shared-brain-landscape-2026.md`.
  - Triangulate with: independent benchmark run on shared corpus.

### Low

- **Five named category competitors from `plan.md` landscape paragraph** (Pinecone,
  Neo4j, LangChain, Cloudflare Agent Memory, Hindsight) — all single-source
  `plan.md`. Recoverable via competitive teardown; not load-bearing until a buyer
  names one.

- **Individual landscape rivals** (Letta, memnos, NEXO, memory-mcp, etc.) — each
  rests on `shared-brain-landscape-2026.md` alone. Interesting for map completeness;
  not quarter-scoping until a design partner mentions them.

---

## Triage recommendation

Validate **Highs in this order**:

1. **Thesis (#1) + willingness-to-pay (#2)** — still zero user evidence after 13
   sources; five discovery interviews can move both in a week and gate everything
   else.

2. **Governance vs graph-depth positioning (#5)** — Cognee's graphify ingestion
   makes this the highest-stakes *new* bet: ask design partners whether they'd
   choose TeamShared for work queue/approvals/capture or Cognee for graph ontology
   — before committing a quarter to either axis.

3. **Shared-brain default (#3)** — cheap to ask, expensive to reverse; GBrain and
   Cognee both default to scoped isolation.

Defer distillation-quality measurement (#4), synthesis investment (#7), and
benchmark publishing (#10) until #1–#2 hold and there is real captured data to
measure against.

The team will plan against whatever it does not question. These are the things to question first.
