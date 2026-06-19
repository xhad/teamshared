---
type: research
title: "GBrain — competitor landscape research"
author: garrytan/gbrain (public repo)
origin: https://github.com/garrytan/gbrain
captured: 2026-06-19
note: >
  External competitor research from GBrain's public README, AGENTS.md, and YC
  RFS cross-reference. Product marketing + architecture claims — not user
  research. Treat as single-source competitive intelligence.
---

# GBrain competitor research

Captured 2026-06-19 from [garrytan/gbrain](https://github.com/garrytan/gbrain)
(23.4k stars, MIT, TypeScript). Garry Tan (YC CEO) positions GBrain as the
production brain behind OpenClaw and Hermes agent deployments.

## Positioning

> Search gives you raw pages. GBrain gives you the answer.

> It's the brain layer your AI agent has been missing — the only one that does
> synthesis, graph traversal, and gap analysis in one box.

> And now it works as a company brain too. Each person on the team gets their
> own slice of the brain, scoped by login. When you query, you only see what
> you're allowed to see — never another person's notes, never another team's
> data.

> If you're building in that space, you might as well build on this.

## Scale claims (Garry's deployment)

> 146,646 pages, 24,585 people, 5,339 companies, 66 cron jobs running
> autonomously.

> My agent ingests meetings, emails, tweets, voice calls, and original ideas
> while I sleep.

## Core differentiators (per GBrain)

### Synthesis layer (`gbrain think`)

> **`gbrain search`** returns the top retrieved pages, ranked by hybrid scoring
> (vector + keyword + RRF + source-tier boost + reranker).

> **`gbrain think`** runs the same retrieval, then composes a synthesized
> answer across the results with explicit citations to the source pages AND
> an honest note on what the brain doesn't know yet. The gap analysis is the
> differentiator.

### Self-wiring knowledge graph (zero LLM on write)

> Every page write extracts entity refs and creates typed edges (`attended`,
> `works_at`, `invested_in`, `founded`, `advises`) with zero LLM calls.

> Benchmarked: P@5 49.1%, R@5 97.9% on a 240-page Opus-generated rich-prose
> corpus, +31.4 points P@5 over its graph-disabled variant.

### Autonomous dream cycle

> Cron-driven enrichment runs while you sleep: dedup people pages, fix
> citations, score salience, find contradictions, prep tomorrow's tasks.

> It's easier to ship a daemon that runs 24/7 to ingest, enrich, and
> consolidate than it is to keep an agent in chat working hard. GBrain is that
> daemon, generalized.

## Architecture

> **Two engines, one contract.** PGLite (Postgres 17 via WASM, zero-config,
> default) for personal brains up to ~50K pages. Postgres + pgvector (Supabase
> or self-hosted) for shared / large / multi-machine deployments.

> **Brain repo is the system of record.** Your knowledge lives in a regular git
> repo (your "brain repo") as markdown files. GBrain syncs the repo into
> Postgres for retrieval.

> GBrain exposes 30+ tools over MCP (stdio and HTTP).

> **43 curated skills.** Routing lives in skills/RESOLVER.md. Skills are
> markdown files (tool-agnostic), packaged as a single skillpack the installer
> drops into your agent workspace.

## Schema packs (typed page taxonomy)

> **gbrain doesn't have a fixed layout.** It ships with bundled schema packs and
> lets you author your own when none fit.

> `gbrain-base-v2` (default) — 15-type DRY/MECE canonical taxonomy: `person`,
> `company`, `media`, `tweet`, `social-digest`, `analysis`, `atom`, `concept`,
> `source`, `deal`, `email`, `slack`, `writing`, `project`, `note`.

## Company brain tutorial

> Set up GBrain as your company brain — federated, multi-user, OAuth-scoped
> institutional memory for a 10-50 person team. About 90 minutes end-to-end.

> We fuzz-tested this across every way you can read the brain (search, list,
> lookup, multi-source reads) and got zero leaks.

## Install / distribution

> GBrain is designed to be installed and operated by an AI agent.

> ~30 minutes to a fully working brain. Database ready in 2 seconds (PGLite,
> no server).

> `gbrain init --pglite` then `claude mcp add gbrain -- gbrain serve` for
> local MCP wiring.

## Job queue (Minions)

> BullMQ-shaped, Postgres-native job queue. Durable subagents (LLM tool loops
> that survive crashes via two-phase pending→done persistence).

## Eval framework

> `gbrain eval longmemeval` runs the public LongMemEval benchmark against your
> hybrid retrieval.

> `gbrain eval retrieval-quality` runs NamedThingBench, which hard-gates the
> named-thing retrieval families so a regression in "find the page this query
> names" fails CI loudly.

## YC RFS adjacency (Tom Blomfield, same market thesis)

> We need Garry's G-Brain, but for every business in the world.

> This isn't a company-wide search or a chatbot over documents. It's a living
> map of how a company works.

> Then AI systems can use that skills file to actually do the work safely and
> consistently.

## Competitive overlap with TeamShared (analyst notes — not gbrain claims)

GBrain and TeamShared both target **shared institutional memory for AI agents**
in the YC "company brain" category. Overlap surfaces:

| Dimension | GBrain (public claims) | TeamShared (internal plan) |
|---|---|---|
| Primary user | Individual power user → company brain | Multi-tenant org from day one |
| Storage model | Git markdown repo + Postgres sync | Postgres/Redis/Mem0 pillars |
| Agent interface | MCP (30+ tools) + CLI | MCP (~70 tools) |
| Synthesis | `gbrain think` with gap analysis | Curator worker + distillation |
| Graph | Auto-link on write, typed edges, traversal | Neo4j optional; `memory_graph_*` |
| Skills/playbooks | 43 markdown skills in skillpack | Procedural playbooks + new skills pillar |
| Security | OAuth scopes, visibility filters, fuzz-tested leaks | RLS, RBAC, org isolation, consent capture |
| Capture | Webhooks, inbox folder, signal detector on every message | Consent-first client-sanitized capture |
| Autonomous loop | Dream cycle cron (66 jobs in Garry's deploy) | Distiller + curator workers |
| Distribution | Agent-install protocol, OpenClaw/Hermes native | Cursor plugin + `install.sh` |

## Gaps GBrain does NOT emphasize (relative to TeamShared plan)

- No explicit **five-pillar** memory taxonomy (working/semantic/episodic/procedural/strategic/work)
- No **human approval queue** for agent writes called out in marketing
- No **work queue** as first-class product surface (TeamShared `work_*` tools)
- **Consent-first capture** is not a headline constraint — ingestion is aggressive by default
- **Multi-org self-service** with email OTP console is not the GBrain story (OAuth/admin dashboard)

## Threat level signals

- **Distribution**: 23.4k GitHub stars, YC CEO author, named in YC RFS, native OpenClaw/Hermes integration
- **Technical depth**: retrieval benchmarks, eval CI gates, schema packs, 331 commits, active issue volume (577 issues)
- **Company brain**: explicit multi-user tutorial with leak fuzz-testing — direct overlap with TeamShared enterprise thesis
- **Synthesis moat**: gap analysis in answers is a differentiated UX TeamShared curator does not yet mirror explicitly
