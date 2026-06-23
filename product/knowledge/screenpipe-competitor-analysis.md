# Screenpipe competitor analysis (mogkit)

Generated via mogkit workflow: source capture → `discovery-query` (×3) →
`tradeoff-frame`. Source: `product/sources/screenpipe-research.md` (public
site + GitHub README). Corpus health: **thin** (single-source vendor/marketing
research — no user interviews, no hands-on deployment in this corpus).

---

## Executive summary

**Screenpipe is not a TeamShared replacement — it is an adjacent ambient-capture
layer for the desktop.** Where TeamShared persists org-scoped durable knowledge
(semantic, episodic, procedural pillars, distillation, wiki), Screenpipe records
*what you saw and heard on your machine* 24/7 into local SQLite and exposes it
via MCP, REST, and trigger-based "Pipes" agents.

The overlap is real but narrow: both ship **MCP servers for coding assistants**
(Cursor, Claude Code) and both sit in the YC "AI memory" zeitgeist (Screenpipe
S26; TeamShared in the company-brain RFS lane). They diverge on **data shape**
(screen frames + transcripts vs structured memory records), **scope** (single
device local-first vs multi-tenant shared brain), and **automation model**
(capture-triggered Pipes vs distiller/curator/workflow workers).

For TeamShared product planning: Screenpipe addresses **"I forgot what I was
looking at Tuesday"** and **meeting/action-item automation** without replacing
recall, org governance, or cross-agent skill propagation. The interesting
question is whether TeamShared should **ingest Screenpipe exports** (or similar
ambient capture) into episodic memory, not whether to compete on screen recording.

---

## discovery-query #1: What problem does Screenpipe solve?

### Findings

**1. Ambient desktop recall — not agent session memory**
- *Confidence: Multi-source (site + README)*
- "you forget what you did last tuesday - screenpipe doesn't" — `screenpipe-research.md`
- Event-driven capture: app switches, clicks, typing pauses → screenshot + accessibility tree — README
- TeamShared captures agent *turns* and distilled facts; it does not record arbitrary screen activity.

**2. Local-first privacy is the primary trust story**
- *Confidence: Multi-source*
- "100% local — your data never leaves your machine" — site
- Exclude apps/windows/URLs at source; on-device PII model scrubs cards/SSNs/keys before save — site
- Custom PII model claimed to beat Google/Microsoft/OpenAI filters at 9ms on-device — README (2026-05-29)
- TeamShared's trust story is org RLS + bearer-scoped writes, not "nothing leaves your laptop."

**3. Pipes turn capture into action, not just search**
- *Confidence: Single-source*
- "Agents that act on your work, not just remember it" — site
- Triggers: `meeting_ended`, schedules; writes to Notion, HubSpot, Linear, Obsidian — site/README
- Per-pipe YAML permissions enforced at OS level (three layers, not prompt-based) — README
- TeamShared automation: distiller → episodic/semantic; curator → wiki; no capture-triggered outbound writes.

**4. MCP is zero-config for screen history queries**
- *Confidence: Single-source*
- `claude mcp add screenpipe -- npx -y screenpipe-mcp@latest` — README
- Example: "what did i see in the last 5 mins?" — README
- TeamShared MCP requires bearer token + `install.sh`; richer surface but higher onboarding friction.

### Gaps

- No evidence on whether developers run Screenpipe *alongside* a team brain vs instead of one.
- Unknown overlap between Screenpipe MCP queries and TeamShared `memory_recall` in real Cursor sessions.
- PII scrub efficacy unvalidated in this corpus (vendor benchmark only).
- Enterprise fleet deployment claims unverified (MDM + per-pipe permissions in production?).

### Discovery questions

1. Do you use ambient screen capture today (Screenpipe, Rewind, Recall)? What do you query it for?
2. When an agent needs context, do you want *what I saw on screen* or *what the team decided last week*?
3. Would you trust 24/7 capture if PII scrubbing is on-device but not auditable by your security team?
4. Do Pipes that write to Linear/Notion replace manual `memory_remember`, or are they separate workflows?

---

## discovery-query #2: How does Screenpipe relate to TeamShared?

### Findings

**1. Orthogonal layers — capture vs durable brain (same pattern as Headroom)**
- *Confidence: Single-source (synthesis)*
- Screenpipe: ambient OS-level ingest → local search/MCP
- TeamShared: agent/human writes → org-scoped pillars → recall/think/wiki/work
- Both reduce agent amnesia; Screenpipe from *observation*, TeamShared from *articulation*.

**2. MCP collision on Cursor — two memory servers, different corpora**
- *Confidence: Single-source*
- Screenpipe MCP: query screen/audio history on localhost
- TeamShared MCP: query org semantic/episodic/procedural memory on teamshared.com
- An agent could hold both; no integration path documented in either corpus.

**3. Enterprise stories diverge: fleet-local vs multi-tenant cloud**
- *Confidence: Single-source*
- Screenpipe Teams: "Admins control what gets captured… They never see the actual data — everything stays on each employee's device" — README
- TeamShared: multi-tenant Postgres, org-scoped API keys, shared brain across agents
- Screenpipe enterprise is **policy + pipes fleet-wide**; TeamShared enterprise is **shared knowledge pool**.

**4. Screenpipe monetizes subscriptions; TeamShared has not productized hosted tiers**
- *Confidence: Single-source*
- $25/mo Standard, $50/seat Pro, $150/seat Enterprise — README
- TeamShared pricing unknown in corpus; GBrain is MIT; Mem0/Zep/Letta monetize cloud.

**5. YC S26 validates "desktop memory" as its own category**
- *Confidence: Single-source*
- "we joined YC S26" — README (2026-05-14)
- Distinct from company-brain RFS (GBrain reference) — ambient personal memory may split buyer attention.

**6. License shift reduces "build on it" parity with GBrain**
- *Confidence: Single-source*
- 2026-06-10: Screenpipe Commercial License — personal non-commercial OK; commercial use requires license — README
- TeamShared and GBrain remain more permissive for self-hosted commercial use (corpus assumption).

### Gaps

- No head-to-head: "summarize my week" via Screenpipe Pipes vs TeamShared episodic timeline + curator wiki.
- Unknown whether Screenpipe Teams customers want a *shared* org brain or only fleet-managed personal capture.
- TeamShared has no screen-capture pillar; unclear if buyers expect it.

### Discovery questions

1. For your team, is memory personal (my screen) or shared (our decisions)? Both?
2. If Screenpipe wrote meeting summaries to Obsidian, would you also `memory_remember` the same facts?
3. Does your security team allow 24/7 screen capture with local-only storage?
4. Would you pay $50/seat for ambient capture + $X for org brain, or one product?

---

## discovery-query #3: What is Screenpipe's technical moat?

### Findings

**1. Event-driven capture efficiency**
- *Confidence: Single-source*
- Accessibility-tree-first (OCR fallback); 5–10% CPU; ~5–10 GB/month — README
- Continuous recording competitors cited as ~2 GB/8hr vs ~300 MB/8hr — README comparison table
- Moat: engineering on OS integration + storage economics, not LLM synthesis.

**2. Custom on-device PII model (screenleak)**
- *Confidence: Single-source (vendor claim)*
- Alpha release 2026-05-29; 9ms on consumer hardware; beats major cloud filters on computer recording data — README
- Enables "capture everything else" default — exclusion list + scrub pipeline.
- TeamShared rejects secrets at write time; no equivalent pre-persistence visual PII pipeline.

**3. Deterministic pipe permissions (three enforcement layers)**
- *Confidence: Single-source*
- YAML frontmatter → skill gating + agent interception + server middleware + per-pipe tokens — README
- Stronger than prompt-based "don't look at 1Password" — relevant for enterprise fleet.
- TeamShared RBAC is org/API-key scoped; not per-tool-call OS-level capture gating.

**4. Pipes as markdown-defined agent fleet**
- *Confidence: Single-source*
- `~/.screenpipe/pipes/` — developer-extensible; shared deployment via Teams admin — README
- Overlaps TeamShared skills/playbooks thesis but sources from *screen events*, not agent traces.

**5. Distribution: 19k★ + YC + paid desktop app**
- *Confidence: Single-source*
- Open-source Rust core auditable; signed app subscription-gated — README + license note
- Faster end-user adoption path than self-hosted Postgres brain.

### Gaps

- No independent security audit of capture + PII pipeline in corpus.
- SQLite FTS5 search quality vs TeamShared hybrid vector+keyword recall unbenchmarked.
- Long-term lock-in risk from commercial license + subscription app vs self-built core.

---

## tradeoff-frame: Should TeamShared integrate ambient desktop capture?

### The decision

Should TeamShared add a capture connector for ambient desktop memory (Screenpipe
REST/MCP export, or native screen ingest), feeding episodic memory?

**Options:**
- **A.** Document Screenpipe as complementary — users run both MCP servers; no integration
- **B.** Ship a Screenpipe → TeamShared ingest connector (meeting summaries, pipe outputs → episodic)
- **C.** Build native ambient capture (screen/audio) inside TeamShared stack
- **D.** Explicitly avoid capture — position TeamShared as "what you and agents *decide* to remember"

### Real axes

1. **Privacy surface** — 24/7 screen capture expands blast radius vs agent-initiated writes
2. **Shared brain promise** — Screenpipe data is device-local; org sharing needs explicit export/consent
3. **Category clarity** — "company brain" vs "digital clone of your desktop"
4. **Engineering cost** — OS capture + PII is a product company (Screenpipe's entire stack)
5. **Enterprise buyer** — security teams may block ambient capture regardless of local storage

### Option profiles

**A — Complementary (status quo)**
- Optimizes: clearest positioning; no capture liability; Cursor can mount both MCPs
- Sacrifices: no unified query; users manually bridge screen memory → team brain

**B — Ingest connector**
- Optimizes: meeting summaries and pipe outputs land in episodic timeline; leverages Screenpipe's capture without building it
- Sacrifices: dependency on third-party commercial license; sync/consent model undefined; duplicate storage

**C — Native capture**
- Optimizes: single vendor story; org-scoped policies on what enters shared brain
- Sacrifices: quarters of OS engineering; competes with YC-funded specialist; distracts from pillar differentiation

**D — Anti-capture positioning**
- Optimizes: trust story for teams who reject surveillance; aligns with agent-initiated `memory_remember`
- Sacrifices: loses "what happened in that call" unless user manually captures; Screenpipe owns that wedge

### Reversibility

**Two-way door** for A and B (connector optional, removable).
**One-way door** for C (infra + privacy commitments).
D is reversible but constrains future capture bets.

### Decisive evidence

- Interview: do target buyers want ambient capture in the *same* product as org memory?
- Security review: would 3/5 design-partner CISOs allow Screenpipe on eng laptops?
- Usage: if users already run Screenpipe + TeamShared, do they duplicate facts or complement?
- WTP: is $50/seat capture + org brain pricing additive or cannibalistic?

Frame the decision. Then make the call yourself, or escalate to whoever owns it.

---

## Comparison matrix (Screenpipe vs TeamShared vs GBrain)

| Dimension | Screenpipe | TeamShared | GBrain |
|---|---|---|---|
| **Primary input** | Screen + audio (ambient) | Agent/human MCP writes + turn capture | Pages, email, meetings, voice (aggressive ingest) |
| **Storage locus** | Local SQLite per device | Cloud/hosted Postgres + Redis | Self-hosted (user infra) |
| **Org sharing** | Fleet policy; data stays on device | Native multi-tenant RLS | Company brain OAuth slices |
| **Agent query** | MCP screen search | MCP recall/think | MCP search/think + gap analysis |
| **Automation** | Pipes (triggered) | Distiller/curator/workflows | Dream cycle + cron |
| **Human surface** | Timeline DVR app | Console wiki + work | Agent-query optimized |
| **Privacy model** | Local + PII scrub + exclude | Org RBAC + write guards | Self-hosted trust |
| **Pricing** | $25–150/seat/mo | Unpublished | MIT OSS |
| **Moat** | Capture efficiency + PII model | Multi-tenant governance + pillars | Synthesis + graph + distribution |

---

## Recommended product responses (not mogkit output — engineering judgment)

1. **Classify Screenpipe as adjacent capture**, not memory competitor #16 — tag
   `ambient-capture` in graph; same shelf as Headroom (orthogonal layer).
2. **Document dual-MCP pattern** — Cursor users may run Screenpipe (what I saw)
   + TeamShared (what the team knows); publish a short integration note.
3. **Spike Option B** — Screenpipe pipe → webhook → TeamShared episodic ingest
   for meeting summaries only; measure duplicate vs net-new facts.
4. **Do not build native screen capture** unless a design partner pays for it —
   Screenpipe has YC + 19k★ + dedicated PII model; TeamShared wins on org brain.
5. **Watch Pipes → Linear/Notion** — overlaps with work queue + curator outputs;
   if buyers automate standups via Screenpipe, TeamShared work/episodic must be
   the system of record or integrate.
6. **Privacy positioning** — TeamShared's agent-initiated capture may be easier
   to sell to enterprise than 24/7 screen record; use Screenpipe contrast in
   security conversations without dismissing the category.

---

## Files touched

- `product/sources/screenpipe-research.md` — new research source
- `product/graph/graph.json` — incremental Screenpipe nodes/edges
- `product/graph/graph.md` — updated summary
- `product/knowledge/screenpipe-competitor-analysis.md` — this document

Answer your question from the findings. Fill the gaps before you commit to positioning.

---

## Next mogkit steps

1. Re-run `graphify` to fully ingest `screenpipe-research.md` into `product/graph/graph.json`.
2. `discovery-query`: "Do buyers conflate ambient desktop memory with company brain?"
3. `interview-guide` — validate capture tolerance vs shared recall for 10–50 person eng teams.
4. `spec-stress-test` — red-team a Screenpipe pipe → TeamShared episodic webhook path.
