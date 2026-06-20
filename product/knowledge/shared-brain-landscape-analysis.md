# Shared brain landscape analysis (mogkit)

Generated via mogkit workflow: `graphify` → `discovery-query` (×2) →
`tradeoff-frame`. Sources: `product/sources/shared-brain-landscape-2026.md`
plus the prior GBrain + YC RFS + internal intent corpus. Corpus health:
**thin** (8 sources, single-perspective competitive intelligence — no
user interviews).

---

## Executive summary

The 2026 "shared brain" landscape is no longer a GBrain-vs-TeamShared
two-horse race. **Hivemind** (Activeloop, Deep Lake) ships the same
skill-codification thesis as TeamShared's skills pillar — but with
auto-mining from captured traces that TeamShared requires manual
authoring for. **Mem0/Zep/Letta** have orders of magnitude more adoption
(55k / 24k / sizable) and all monetize hosted tiers ($19/$25/$249),
which TeamShared has not yet productized. **Graphiti/Zep** hold a
legitimate moat on bi-temporal fact validity (point-in-time queries)
that TeamShared cannot answer without an architectural change.

TeamShared's defensible ground narrows to: **multi-tenant org
infrastructure with server-side conversation capture middleware and the
five-pillar memory taxonomy**. None of the named rivals combine all three. The biggest untested bets the new
landscape exposes: (1) is the manual `memory_skill_set` authoring loop
enough, or must TeamShared auto-mine skills from traces? (2) do buyers
actually need bi-temporal fact validity? (3) does TeamShared need a
published benchmark number to compete?

---

## discovery-query #1: Where does TeamShared win vs Hivemind on the skills pillar?

> Corpus health: **thin**. Most of this answer is gaps; that is the
> correct, useful result.

### Findings

**1. Both products pitch the same thesis: skills compound across the team**
- *Confidence: Multi-source*
- Hivemind: "It mines your team's traces for repeated patterns and
  codifies them into reusable skills that propagate back into every
  agent on the team. The agent your junior engineer used this morning
  is sharper because of what your senior engineer's agent figured out
  last week." — `shared-brain-landscape-2026.md`
- TeamShared: skills pillar + procedural playbooks, `memory_skill_set`
  MCP tool (catalog confirmed).

**2. Hivemind auto-mines skills from captured traces; TeamShared requires explicit `memory_skill_set` calls**
- *Confidence: Single-source*
- "A background worker mines traces for repeated patterns and
  codifies them into `SKILL.md` files, scoped to your workspace." —
  `shared-brain-landscape-2026.md`
- TeamShared: `memory_skill_set` is agent-discretionary ("called when
  the model decides to" — same limitation memnos flags for plain MCP
  capture). Graph node `feature-hivemind-skill-codify` has no
  TeamShared-side equivalent feature node for auto-mining.

**3. Hivemind captures every session prompt/tool-call/response as structured traces; TeamShared capture is server-side middleware but capture-enabled is gated**
- *Confidence: Single-source*
- "Captures every session's prompts, tool calls, and responses as
  structured traces in Deeplake" — `shared-brain-landscape-2026.md`
- TeamShared: "a `ToolCallCaptureMiddleware` plus the `POST /sessions/turns`
  ingest endpoint record turn-by-turn natural-language conversation
  across harnesses (gated by `capture_enabled`)" — `AGENTS.md`
- Both ship auto-capture; Hivemind's is on by default for the listed
  harnesses, TeamShared's is feature-gated.

**4. Hivemind is newer but had 1,100+ GitHub stars in its first day; TeamShared adoption numbers are not in the corpus**
- *Confidence: Single-source*
- "The project has garnered over 1,100 GitHub stars in its first day,
  signaling strong interest from the developer community." —
  `shared-brain-landscape-2026.md`
- TeamShared's strategic KPI is "Reach 500 weekly active agents writing
  to shared memory" (from prior memory_recall) — current value unknown.

### Gaps

- No interview with a team that chose Hivemind over TeamShared (or vice versa).
- TeamShared's auto-skill-mine roadmap position is unknown — could be planned, could be absent.
- No head-to-head on skill quality: Hivemind's Haiku-driven mining vs TeamShared's explicit authoring.
- Hivemind pricing beyond "free tier" is unspecified in the corpus.
- Whether the assumption `assumption-auto-skill-mine-not-needed` is a deliberate bet or an unexamined gap is itself unknown.

### Discovery questions

1. Walk me through the last skill your team codified into agent memory — did you write it by hand, or did the agent mine it from a recurring trace? What broke either way?
2. When you compare Hivemind's auto-codified `SKILL.md` files against TeamShared's explicitly-authored skills, which felt more trustworthy to ship to the whole team? Why?
3. Has your team ever rejected an auto-mined skill because it captured the wrong pattern? What happened to the agent that propagated it?

---

## discovery-query #2: Does the broader 2026 landscape invalidate the GBrain-only positioning?

> Corpus health: **thin**.

### Findings

**1. GBrain is no longer the only direct rival; Hivemind ships the same shared-brain pitch**
- *Confidence: Multi-source*
- Hivemind: "Auto-learning, cloud-backed shared brain for Claude Code •
  OpenClaw • Codex • Cursor • Hermes • pi agents." — `shared-brain-landscape-2026.md`
- multi-agent-memory (CMPSBL): "Multi-Agent Memory gives your AI agents
  a shared brain that works across machines, tools, and frameworks." —
  `shared-brain-landscape-2026.md`
- The category now has multiple products using the exact "shared brain"
  phrasing TeamShared was positioning against GBrain alone with.

**2. The hosted platforms (Mem0/Zep/Letta) all monetize and have far larger adoption**
- *Confidence: Single-source*
- "Mem0 wins on speed of adoption and ecosystem (~55k GitHub stars as
  of May 2026)." — `shared-brain-landscape-2026.md`
- Zep: "$25/mo — full Graphiti engine, temporal graph, entity
  resolution." — `shared-brain-landscape-2026.md`
- Letta: "Pro / $20/mo / Up to 20 stateful agents." —
  `shared-brain-landscape-2026.md`
- TeamShared: hosted at teamshared.com but no pricing tier surfaced in
  the corpus; assumption `assumption-buyers-pay-for-memory-infra`
  remains unvalidated.

**3. The fact-vs-event distinction is now a category-wide intuition, not a TeamShared differentiator**
- *Confidence: Multi-source*
- multi-agent-memory: "treat memory as a flat key-value store without
  understanding that a fact and an event are fundamentally different
  things" — `shared-brain-landscape-2026.md`
- memnos: "distilled into facts, and recalled in later sessions" —
  `shared-brain-landscape-2026.md`
- TeamShared: `MemoryKind` enum (fact | event | preference | note |
  ...). The five-pillar model remains broader, but the fact/event
  split alone is no longer novel.

**4. MCP is the de facto standard; every serious player exposes memory through MCP**
- *Confidence: Single-source*
- "OpenMemory MCP from Mem0, Anthropic Memory Tool, Graphiti MCP
  server, Neo4j Agent Memory Service — all expose memory through MCP." —
  `shared-brain-landscape-2026.md`
- TeamShared's `feature-mcp-native` is now table stakes, not a
  differentiator.

**5. GBrain remains the only competitor with multi-source evidence; the others are single-source vendor claims**
- *Confidence: Assumed*
- GBrain has 2 sources (gbrain research + YC RFS); the 11 new rivals
  each have 1 source. The landscape is rich on paper but the buyer
  preference signal is unchanged.

### Gaps

- No interviews with teams that chose Mem0/Zep/Letta over a "shared brain" server.
- No evidence that buyers perceive "shared brain" servers (Hivemind, multi-agent-memory, teamshared) as a distinct category from "memory platforms" (Mem0/Zep/Letta) — they may collapse into one buying decision.
- TeamShared pricing not in corpus; cannot assess where it lands vs $19/$25/$249 tiers.
- TeamShared adoption numbers (the 500-WAA KPI) not in corpus.
- Whether the assumption `assumption-gbrain-is-primary-competitor` was a deliberate narrow focus or an artifact of single-source research is itself unknown.

### Discovery questions

1. When you evaluated agent memory, did you look at hosted platforms (Mem0/Zep/Letta) separately from "shared brain" servers (Hivemind, multi-agent-memory), or were they one shortlist?
2. What was the single thing that made you rule out Mem0/Zep/Letta — was it pricing, the per-agent (not team-shared) model, or something else?
3. At what team size did the per-agent memory model start feeling like a handicap vs a shared brain?

---

## tradeoff-frame: How should TeamShared respond to Hivemind's auto-skill-mine loop?

### The decision

Should TeamShared build an auto-trace-to-skill miner (Hivemind's
headline feature), keep the explicit `memory_skill_set` authoring
model, or do something between?

**Options:**
- **A.** Build the full Hivemind-style auto-miner: background worker mines captured traces and writes candidate `SKILL.md` files for review.
- **B.** Keep explicit authoring; add a "skill suggestions" surface that surfaces trace patterns to the human who decides whether to call `memory_skill_set`.
- **C.** Keep explicit authoring unchanged; compete on managed multi-tenant governance and the five-pillar model instead.
- **D.** Partner/integrate: accept Hivemind-mined skills as input through the existing `memory_skill_set` tool.

### Real axes

1. **Trust model** — auto-mined skills propagate to every agent on the team; a wrong pattern becomes every agent's default. Hivemind accepts this; TeamShared's governance model (approvals queue, RBAC) may not.
2. **Engineering cost** — A is a background worker + LLM mining loop + review UI; B is a suggestions surface; C is zero; D is adapter work.
3. **Capture dependency** — auto-mining is only as good as capture. TeamShared's capture is gated by `capture_enabled`; Hivemind's is on by default for supported harnesses.
4. **Differentiation** — Hivemind has the auto-mine moat today; matching it removes the gap but doesn't differentiate. Competing on governance + pillars keeps a distinct shape.
5. **Strategic KPI** — the KPI is "500 weekly active agents writing to shared memory." Manual `memory_skill_set` is high-friction; auto-mining could raise WAA but at the cost of skill quality.

### Option profiles

**A — Full auto-miner**
- Optimizes: closing the visible feature gap with Hivemind; potentially raising WAA via lower-friction skill creation.
- Sacrifices: the governance constraint (auto-mined skills propagate without per-skill approval); engineering bandwidth; skill quality (Haiku-grade mining may produce noisy skills).

**B — Suggestions surface**
- Optimizes: keeping the human-in-the-loop governance model while reducing authoring friction; a middle path that matches Hivemind's mining insight without the propagation risk.
- Sacrifices: some of the "it just works" magic of Hivemind's auto-propagation; still requires building the mining + suggestion UI.

**C — Compete on governance + pillars**
- Optimizes: a distinct shape in the category; conserves engineering bandwidth for the strategic KPI work.
- Sacrifices: the visible feature gap with Hivemind remains; may lose buyers who expect auto-mining as table stakes.

**D — Accept Hivemind-mined skills as input**
- Optimizes: compositing with Hivemind rather than competing head-on; lets teams use both.
- Sacrifices: positions TeamShared as a downstream store, not a peer; may cede the skill-codification story entirely.

### Reversibility

- **A** is one-way (auto-mining + propagation infra is a long bet; pulling it back confuses users who built workflows around it).
- **B** is two-way (suggestions can graduate to auto-propagate later; can be retired without breaking existing skills).
- **C** is two-way but slow; the gap compounds if Hivemind's auto-mine becomes the category default.
- **D** is two-way but positions TeamShared as derivative.

### Decisive evidence

- 3 design-partner interviews where teams **chose Hivemind specifically for the auto-mine** and explain why TeamShared's manual authoring wouldn't work (validates A).
- An interview where a team **rejected Hivemind's auto-mined skills as untrustworthy** and preferred explicit authoring (validates C).
- A buyer saying "we'd adopt TeamShared **only if** skills compound automatically across the team" (validates A or B).
- Recall-quality benchmark showing auto-mined skills degrade agent performance vs hand-authored ones (validates C).

**Unspoken axis:** Hivemind is a week old at the time of capture. The
auto-mine feature may not survive contact with production. TeamShared's
slow bet on explicit authoring may be correct — but only if buyers
don't default to Hivemind in the meantime.

---

## Recommended product responses (not mogkit output — engineering judgment)

These are implications, not mogkit recommendations:

1. **Decide the auto-skill-mine question deliberately.** It's the single
   biggest untested bet in the corpus. Option B (suggestions surface)
   preserves the governance constraint while closing the visible gap
   — worth scoping before assuming A or C.
2. **Re-positioning: GBrain-only framing is stale.** The category brief
   and any external positioning should name Hivemind as the direct
   shared-brain rival and Mem0/Zep/Letta as the hosted-platform
   alternatives. The README's "GBrain is the primary named competitor"
   line should be updated.
3. **Publish a benchmark number** — even a small NamedThingBench-style
   suite on TeamShared's RRF recall. The "reliable enough to trust"
   strategic KPI is unprovable without one, and every rival has a
   number.
4. **Surface pricing.** Mem0 ($19/$249), Zep ($25/$475), Letta ($20).
   TeamShared's willingness-to-pay assumption is untestable while
   pricing is invisible.
5. **Don't chase bi-temporal.** Graphiti's valid_from/invalid_at is a
   real moat but a large architectural bet. Document it as a known gap
   and let the curator's page-rewriting compensate until buyer demand
   surfaces.

---

## Files touched

- `product/sources/shared-brain-landscape-2026.md` — new research source
- `product/graph/graph.json` — re-graphified with landscape nodes/edges (91 nodes, 52 edges)
- `product/graph/graph.md` — updated summary
- `product/knowledge/shared-brain-landscape-analysis.md` — this document

answer your question from the findings. fill the gaps before you commit to anything.
