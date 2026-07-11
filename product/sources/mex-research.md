---
type: research
title: "mex — repo-scoped agent memory research"
author: mex-memory/mex (public repo + launchx.page)
origin: https://github.com/mex-memory/mex
captured: 2026-06-26
note: >
  External product/architecture research from mex-memory/mex README, launchx.page,
  GitHub issues/PRs, and npm package metadata. Vendor claims on token reduction
  and drift scoring — not user research. mex is *per-repo markdown scaffold +
  drift CLI*, not a multi-tenant org brain. MIT, ~1.1k GitHub stars (Jun 2026).
---

# mex — repo-scoped agent memory research

Captured 2026-06-26 from [mex-memory/mex](https://github.com/mex-memory/mex)
(~1,142 GitHub stars, MIT, TypeScript primary, npm `mex-agent` v0.6.2). Marketing
site: [launchx.page/mex](https://launchx.page/mex). Org: `mex-memory` (README
badges still reference `theDakshJaitly/mex` — likely org migration).

mex's category: **persistent project memory for AI coding agents** — a structured
markdown scaffold in-repo plus a CLI that detects when that scaffold drifts from
the real codebase. Not durable team knowledge infrastructure — it keeps *this
repo's* agent context honest and routable.

## Positioning

> "AI agents forget everything between sessions. mex gives them permanent,
> navigable project memory so every session starts with the right context instead
> of a cold prompt dump."

> "Most agent memory setups become one giant instruction file. That works for a
> while, then it floods the context window, burns tokens, and drifts away from
> the real codebase."

Compared to TeamShared: mex does not pitch multi-tenant org scoping, five memory
pillars, distillation workers, or a human console wiki — it pitches **git-local
markdown routing + token-efficient context loading + zero-token drift detection**.

## Core loop

```
npx mex-agent setup → scaffold (ROUTER.md, context/, patterns/) → agent loads routed files
→ mex check (11 drift checkers, no AI) → mex sync (targeted AI fix prompts) → mex log (jsonl events)
```

From README:

> "The agent starts with a tiny auto-loaded file. That file points to `ROUTER.md`,
> and the router loads only the context needed for the current task. After
> meaningful work, the GROW step updates project state, decisions, and task
> patterns so the scaffold becomes more useful over time."

## Scaffold structure

| Path | Role |
|------|------|
| `AGENTS.md` / `CLAUDE.md` / `.cursorrules` | Tiny tool-loaded anchor (~120 tokens) |
| `.mex/ROUTER.md` | Task-type → context file routing table |
| `.mex/context/` | architecture, stack, setup, decisions, conventions |
| `.mex/patterns/` | Reusable task guides with gotchas + verify steps |
| `.mex/events/decisions.jsonl` | Append-only notes via `mex log` |

Setup supports: Claude Code, Cursor, Windsurf, Copilot, OpenCode, Codex.

## Drift detection (claimed moat)

Eleven checkers validate scaffold against codebase. **Zero tokens, zero AI.**

| Checker | What it catches |
|---------|----------------|
| path | Referenced file paths missing on disk |
| edges | YAML frontmatter edge targets → missing files |
| index-sync | `patterns/INDEX.md` out of sync |
| staleness | Files not updated in 30+ days or 50+ commits |
| command | `npm run X` / `make X` scripts that don't exist |
| dependency | Claimed deps missing from package.json |
| cross-file | Same dependency, different versions across files |
| script-coverage | package.json scripts not mentioned in scaffold |
| tool-config-sync | CLAUDE.md / .cursorrules out of sync |
| todo-fixme | Unresolved TODO/FIXME in scaffold markdown |
| broken-link | Local markdown links that don't exist |

Scoring: starts at 100; −10 per error, −3 per warning, −1 per info.

> "`mex sync` — Detect drift, choose mode, let AI fix, verify, repeat"

## CLI surface (selected)

| Command | Purpose |
|---------|---------|
| `mex setup` | Create `.mex/` scaffold + AI populate |
| `mex setup --mode agent-memory` | Persistent-agent / homelab workspace templates + `HEARTBEAT.md` |
| `mex check` / `mex check --json` | Drift report |
| `mex sync` | Targeted fix prompts for stale files only |
| `mex init` | Pre-scan codebase → structured brief for AI |
| `mex log` / `mex timeline` | Append-only event log |
| `mex heartbeat` | Lightweight persistent-agent health (stale frontmatter) |
| `mex watch` | Post-commit hook or interval heartbeat |
| `mex` / `mex tui` | Interactive terminal dashboard |

npm package: **`mex-agent`** (CLI command still `mex`; name taken on npm).

## Agent memory mode (persistent agents)

> "`mex setup --mode agent-memory` creates a scaffold for persistent agents whose
> 'project' is an operational environment rather than a code repo."

> "`mex heartbeat` is intentionally lighter than `mex check`: it reads
> `last_updated` frontmatter and memory cleanup metadata, prints `HEARTBEAT_OK`
> when clean"

Community benchmark (OpenClaw homelab, vendor-cited): 10/10 scenarios passed,
drift score 100/100, ~60% average token reduction per session.

| Scenario | Without mex | With mex | Saved |
|----------|-------------|----------|-------|
| "How does K8s work?" | ~3,300 tokens | ~1,450 tokens | 56% |
| "Open UFW port" | ~3,300 tokens | ~1,050 tokens | 68% |

## MCP server (in flight)

Issue [#81](https://github.com/mex-memory/mex/issues/81) — maintainer prefers
Option B (import `mex-agent` public API directly, not subprocess wrap).

Draft PR [#84](https://github.com/mex-memory/mex/pull/84) (`packages/mex-mcp`,
stdio, **draft/open** as of 2026-06-18):

| Tool | Returns |
|------|---------|
| `mex_check` | DriftReport (score, issues, filesChecked) |
| `mex_log` | events array / `{ ok }` |
| `mex_timeline` | filtered events |
| `mex_heartbeat` | HeartbeatResult |
| `mex_read_file` | raw scaffold file content |

`mex_sync` deferred until structured return shape settled. Maintainer
(`theDakshJaitly`) indicated they may ship MCP themselves; community PR welcome.

Suggested agent boot sequence (issue #81): `mex_check` + `mex_read_file("ROUTER.md")`.

## Distribution & monetization

- **GitHub:** ~1,142 stars, 65 forks, created 2026-03-21, active through v0.6.2 (2026-06-22)
- **npm:** `mex-agent` published May–Jun 2026 (0.3.5 → 0.6.2)
- **License:** MIT
- **Topics:** claude-code, cursor, codex, context-management, memory-management, typescript
- **LaunchX:** launchx.page/mex sells premium Next.js boilerplates with "production-grade
  memory baked in" — commercial upsell adjacent to OSS CLI
- **Telemetry:** opt-out anonymous usage (command, version, OS — not paths/content);
  `DO_NOT_TRACK=1` / `MEX_TELEMETRY=0`

## Supported tools / install path

```bash
npx mex-agent setup
# optional: npm install -g mex-agent
```

Per-tool config files with identical content: `CLAUDE.md`, `.cursorrules`,
`.windsurfrules`, `.github/copilot-instructions.md`, `AGENTS.md`.

Windows: recommended `npx` flow; legacy `setup.sh` requires WSL/Git Bash consistency
(issue #10).

## Landscape placement (TeamShared taxonomy)

Fits **Tier 3 — Git-native / repo-scoped memory** alongside xChuCx/agent-memory
(per shared-brain-landscape-2026.md). Not Tier 1 company brain (GBrain) or Tier 2
hosted memory API (Mem0/Zep).

Differentiators vs xChuCx/agent-memory (from landscape doc): mex emphasizes **drift
detection + context routing + token economics**; agent-memory emphasizes **branch-aware
git sync, secret scanning, human review gate, federation to landscape stores**.

## Open issues / roadmap signals

- MCP server (#81, PR #84)
- `mex export` — bundle scaffold to single markdown (#56, #72)
- Frontmatter completeness checker (#53, #62)
- Stale-pattern / orphan patterns checker (#51, #64)
- Native Windows PowerShell setup (#11)
- pyproject.toml / Cargo.toml / go.mod dependency parsing (#3)
