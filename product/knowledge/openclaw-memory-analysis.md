# OpenClaw memory analysis (mogkit)

Generated via mogkit workflow: source capture → `discovery-query` (×3) →
`tradeoff-frame`. Source: `product/sources/openclaw-memory-research.md`
(public docs at [docs.openclaw.ai/concepts/memory](https://docs.openclaw.ai/concepts/memory),
plus dreaming and memory-wiki plugin docs). Corpus health: **thin** (public docs
only — no hands-on OpenClaw install, no user interviews).

---

## Executive summary

**OpenClaw native memory is not a TeamShared replacement in the “company brain”
sense — it is the default *personal-agent, file-local* memory layer for the
OpenClaw harness.** Storage is explicit markdown in `~/.openclaw/workspace`:
`MEMORY.md` (long-term bootstrap), `memory/YYYY-MM-DD.md` (daily working notes),
optional `DREAMS.md` (dreaming review).

TeamShared is a **multi-tenant org brain** (Postgres pillars, Redis working
memory, distiller/curator workers, MCP + console). The competitive fight on
OpenClaw is not `memory-core` vs TeamShared — it is **GBrain/Cognee vs TeamShared
for the external MCP slot**, with native file memory as the solo-user baseline.

---

## discovery-query #1: What problem does OpenClaw memory solve?

### Findings

**1. Agent amnesia with zero hidden state**
- *Confidence: Multi-source (OpenClaw docs)*
- “The model only remembers what gets saved to disk; there is no hidden state.”
- `MEMORY.md` bootstraps every session; daily notes are indexed but not always injected.
- TeamShared: memory exists server-side whether or not the agent remembered to write.

**2. Two-tier memory: curated long-term vs working daily notes**
- *Confidence: Multi-source*
- `MEMORY.md` = compact facts/preferences/decisions (not raw transcript).
- `memory/YYYY-MM-DD.md` = detailed observations; searchable via `memory_search`.
- TeamShared maps to semantic vs working→episodic (Redis → distiller).

**3. Context loss at compaction**
- *Confidence: Single-source*
- Memory flush: silent turn before compaction reminds agent to persist to files (on by default).
- TeamShared: `context_commit`, `context_prepare`, MCP middleware — server-side compression path.

**4. Promotion without manual curation (dreaming)**
- *Confidence: Multi-source (memory + dreaming docs)*
- Opt-in cron: light → REM → deep; threshold gates on score, recall count, query diversity.
- Only deep phase writes `MEMORY.md`; `DREAMS.md` is human review surface.
- TeamShared distiller + curator — less explicit promotion scoring, richer pillar routing.

**5. Action boundaries, not just facts**
- *Confidence: Single-source*
- Action-sensitive memories capture when it is safe to act (approvals, expiry, handoffs).
- Memory preserves context but does not enforce policy — approvals are separate controls.
- TeamShared: RBAC + guarded writes; approvals console UI partially deferred.

**6. Short-lived follow-ups vs durable facts**
- *Confidence: Single-source*
- Commitments: inferred, channel-scoped, delivered via heartbeat.
- TeamShared: `work_*` for tasks; no inferred commitment layer shipped.

**7. Pluggable backends and hybrid search**
- *Confidence: Single-source*
- Default `memory-core`: SQLite + vector + keyword. Plugins: QMD, Honcho, LanceDB.
- `memory-wiki` adds claims/evidence belief layer beside active plugin.

### Gaps

- Unknown % of OpenClaw users on native memory vs external MCP brain.
- No recall benchmark vs TeamShared pgvector on identical corpus.
- Git-reviewable memory preference unvalidated in design partners.

### Discovery questions

1. On OpenClaw, do you use built-in file memory, an MCP brain, or both?
2. When memory fails, is it “forgot to write the file,” bad search, or wrong workspace?
3. Would you trust dreaming auto-promotion into `MEMORY.md`?
4. Do you need memory in git PRs or a hosted org brain?

---

## discovery-query #2: How does OpenClaw memory relate to TeamShared?

### Findings

**1. Harness vs brain — complementary by default**
- *Confidence: Multi-source (openclaw-memory-research + shipped-state)*
- OpenClaw owns runtime (sessions, compaction, heartbeat, plugins).
- TeamShared wires via `install.sh` (`openclaw` agent type, MCP + optional gateway).
- Local scratch + org durable brain is a valid layered pattern (like mex + TeamShared).

**2. GBrain is incumbent “production brain” on OpenClaw**
- *Confidence: Multi-source (gbrain-competitor-research)*
- Garry Tan positions GBrain behind OpenClaw/Hermes.
- TeamShared competes for MCP slot, not for replacing `memory-core` defaults.

**3. `memory-wiki` peers TeamShared wiki/ontology**
- *Confidence: Single-source (memory-wiki docs + shipped-state)*
- Claims, evidence, contradiction/stale dashboards, `wiki_search` / `wiki_get`.
- TeamShared: curator `wiki_pages`, ontology console — org-scoped server-native.

**4. TeamShared wins team primitives OpenClaw memory lacks**
- *Confidence: Single-source (internal shipped-state)*
- Work queue, projects, OKRs, multi-org console, cross-agent shared recall, server capture.

**5. TeamShared wins context compression as MCP service**
- *Confidence: Single-source (internal)*
- `context_*` tools + gateway path vs harness-internal flush + compaction.

**6. OpenClaw wins inspectability and offline portability**
- *Confidence: Multi-source*
- Plain markdown in workspace; `openclaw memory promote-explain`, `doctor`.
- TeamShared: Postgres/Redis — better for teams, weaker for “read MEMORY.md in git.”

### Gaps

- No “disable memory-core, TeamShared-only” best-practice doc.
- Duplicate-fact precedence when both systems active — undocumented.
- `memory_think` gap analysis vs OpenClaw record search — not compared.

### Discovery questions

1. If you use OpenClaw + TeamShared MCP, is native `MEMORY.md` still maintained?
2. Would you pay for hosted TeamShared if file memory is “free enough” solo?
3. Do humans browse memory-wiki dashboards or only agents search?

---

## discovery-query #3: What is OpenClaw memory’s technical moat?

### Findings

**1. File-native SOtR with bootstrap budget discipline**
- *Confidence: Multi-source*
- `MEMORY.md` always injected at session start; truncation signals over-budget curation.
- TeamShared lacks always-in-context compact layer without client `memory_assemble_context`.

**2. Dreaming as scored, reviewable promotion**
- *Confidence: Multi-source (dreaming docs)*
- Six weighted signals + phase reinforcement; `memory promote-explain` CLI.
- TeamShared distiller is batch LLM summarization — less transparent scoring.

**3. Plugin ecosystem without forking harness**
- *Confidence: Single-source*
- Swap memory backend; add memory-wiki; corpus `all` spans wiki + memory.
- TeamShared is monolithic server — not a plugin inside OpenClaw.

**4. Lifecycle hooks tied to agent runtime**
- *Confidence: Multi-source*
- Memory flush ↔ compaction; commitments ↔ heartbeat; dreaming ↔ cron.
- Memory wired into *when the agent runs*, not only when it chooses MCP tools.

**5. Action-sensitive memory as product concept**
- *Confidence: Single-source*
- First-class guidance for timing/authority/expiry on writes.
- TeamShared could adopt as write-tool documentation pattern.

### Gaps

- Per-agent vault isolation ≠ org RBAC; enterprise trust story unmeasured.
- No public eval suite for memory-core like GBrain’s NamedThingBench.
- Plugin backend choice (Honcho multi-agent) unverified vs TeamShared cross-agent recall.

### Discovery questions

1. Does dreaming reduce bad promotions vs manual `MEMORY.md` editing?
2. Is SQLite hybrid search sufficient at 10k+ notes vs hosted pgvector?
3. Is markdown-on-disk the real moat, or plugin backends?

---

## Head-to-head matrix

| Dimension | OpenClaw native memory | TeamShared | Edge |
|---|---|---|---|
| **Primary user** | Solo / homelab persistent agent | Engineering team, multi-agent org | Depends on buyer |
| **Storage SOtR** | Markdown files in workspace | Postgres + Redis | OpenClaw inspectability |
| **Session bootstrap** | Inject `MEMORY.md` (+ recent daily notes) | Rule + `memory_recall` / `context_prepare` | OpenClaw always-on |
| **Working layer** | Daily markdown files | Redis working memory | Tie (different shape) |
| **Long-term promotion** | Dreaming → `MEMORY.md` | Distiller → semantic/episodic | OpenClaw scoring transparency |
| **Knowledge wiki** | `memory-wiki` plugin (claims/evidence) | Curator + `/app/wiki` + ontology | Converging; TeamShared org-native |
| **Search tools** | `memory_search`, `memory_get` | `memory_recall`, `memory_think`, entity hub | TeamShared breadth |
| **Team workflow** | Commitments + cron | `work_*`, projects, OKRs | TeamShared |
| **Multi-tenant** | Per-agent vault (wiki) | RLS, org switcher, API keys | TeamShared |
| **Capture** | Session transcripts → dreaming | Server middleware + session tools | Different defaults |
| **Compression** | Pre-compaction memory flush | `context_*` MCP + gateway | TeamShared as service |
| **Distribution** | OpenClaw harness footprint | `install.sh` + Cursor plugin | OpenClaw harness |
| **External brain** | GBrain default narrative | TeamShared MCP option | GBrain today |

---

## tradeoff-frame: How should TeamShared relate to OpenClaw native memory?

### The decision

Should TeamShared **replace**, **coexist with**, or **ignore** OpenClaw built-in
file memory when selling to OpenClaw users?

**Options:**

- **A. Replace** — Document “OpenClaw + TeamShared only”; discourage `memory-core`.
- **B. Coexist (layered)** — Local scratch + TeamShared org brain with precedence rules.
- **C. Bridge** — TeamShared ingests/exports OpenClaw markdown artifacts.
- **D. Harness-only** — Treat OpenClaw as install channel; don’t compete on file semantics.

### Real axes

1. **Solo vs team** — file memory shines personal; TeamShared shines org recall.
2. **Inspectability vs governance** — workspace files vs server audit/RBAC.
3. **Promotion philosophy** — dreaming scored promotion vs distiller batch.
4. **Distribution** — GBrain owns “OpenClaw brain” narrative unless TeamShared claims team wedge.
5. **Duplication cost** — two brains writing same facts confuses agents.

### Option profiles

**A — Replace**
- Optimizes: one SOtR, clear positioning.
- Sacrifices: bootstrap/offline benefits; fights OpenClaw + GBrain defaults.

**B — Coexist**
- Optimizes: homelab → team upgrade path.
- Sacrifices: requires documented precedence (“org facts in TeamShared; local in MEMORY.md”).

**C — Bridge**
- Optimizes: git-reviewable markdown portability.
- Sacrifices: engineering cost; blurs managed SaaS story.

**D — Harness-only**
- Optimizes: focus on GBrain competitive battle, install parity.
- Sacrifices: ignores memory-wiki/dreaming UX learnings.

### Reversibility

- **A** hard to walk back once users rely on local files.
- **B** two-way; matches mex/Headroom adjacency framing.
- **C** two-way but expensive.
- **D** two-way but leaves differentiation implicit.

### Decisive evidence

- 5 OpenClaw users explaining native memory vs MCP brain usage.
- Duplicate-rate when both systems active on same facts.
- Buyer: “git-reviewed memory” (B/C) vs “org work queue” (B/D).
- Dreaming vs distiller quality on same session transcripts.

**Unspoken axis:** OpenClaw docs teach *memory = markdown you control*. TeamShared
must answer “why not just `MEMORY.md`?” for every OpenClaw eval.

---

## Recommended product responses (not mogkit output — engineering judgment)

1. **Publish “OpenClaw + TeamShared” layering guide** — `MEMORY.md` vs MCP recall precedence; extend `plugins/teamshared/install/openclaw/commands.sh`.
2. **Borrow action-sensitive memory guidance** into `teamshared.mdc` / write-tool docs.
3. **Close synthesis gap** (`memory_think` + gaps/staleness) — OpenClaw users comparing to GBrain `think` won’t care that file memory is simpler.
4. **Study memory-wiki contradiction/stale dashboards** for curator/ontology UX.
5. **Dreaming-inspired promotion transparency** — distiller “why promoted” metadata akin to `memory promote-explain`.
6. **Do not chase file-native SOtR as primary** — moat is org governance + shared recall.

---

## Files touched

- `product/sources/openclaw-memory-research.md` — new research source
- `product/graph/graph.json` — incremental OpenClaw memory nodes/edges
- `product/graph/graph.md` — updated summary
- `product/knowledge/openclaw-memory-analysis.md` — this document

---

## Next mogkit steps

1. Re-run `assumption-audit` after graphify ingest.
2. `discovery-query`: “Do OpenClaw users treat native memory as sufficient for team work?”
3. Combined `tradeoff-frame` with GBrain analysis — **GBrain vs TeamShared on OpenClaw**.
4. Design-partner interviews with OpenClaw/Hermes homelab operators.
