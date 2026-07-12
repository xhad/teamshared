---
type: research
title: "RACT — agentic coding tool research"
author: LucRoot/RACT (public repo + lucroot.github.io)
origin: https://github.com/LucRoot/RACT
captured: 2026-07-11
note: >
  External product/architecture research from LucRoot/RACT README, docs/ARCHITECTURE.md,
  docs/PHILOSOPHY.md, and GitHub metadata. Vendor claims on anti-rot tooling and
  signed receipts — not user research. RACT is a *CLI-first agentic coding harness*
  with anti-rot verifiers and MCP consumer support — not a multi-tenant org brain.
  PolyForm Noncommercial 1.0.0; ~3 GitHub stars (Jul 2026).
---

# RACT — agentic coding tool research

Captured 2026-07-11 from [LucRoot/RACT](https://github.com/LucRoot/RACT)
(~3 GitHub stars, PolyForm Noncommercial 1.0.0, Python 3.11/3.12, PyPI `rootact`
v0.1.1 Jul 2026). Landing: [lucroot.github.io/RACT](https://lucroot.github.io/RACT/).
Author: Dr. Lucas Root, Ph.D.

RACT's category: **model-agnostic, local-first agentic coding** — a terminal harness
that turns intent into validated plans, executes through routed LLM providers, writes
artifacts with a **Root Knot** continuity sentinel, and ships first-class **anti-rot**
CLI verbs (consolidate, novelty scan, auction, fence). Not durable team knowledge
infrastructure — it owns the *build loop* and *codebase hygiene* for one checkout.

## Positioning

> "Model-agnostic, local-first agentic coding with signed receipts and an anti-rot
> verifier arsenal."

> "A 2024 analysis of **623 million commits** by GitClear and GitKraken found that
> AI-assisted code is already rotting codebases: more copy/paste, less refactoring,
> and a measurable decline in code movement."

Compared to TeamShared: RACT does not pitch multi-tenant org scoping, five memory
pillars, distillation workers, or a human console wiki — it pitches **CLI sovereignty,
provider routing, signed run receipts, and measurable defense against code rot**.
README positions directly against **Cursor, Claude Code, and Lovable** (IDE/hosted
coding agents), not against GBrain/Cognee-style memory platforms.

## Core loop

```
intent → Manager (small LM) → Plan → Executor → provider router → artifacts on disk
→ SignatureGuardian (Root Knot) → RunReporter (signed receipt)
Optional: --loop → LoopController + ProgressOracle + MilestoneOracle + HandshakeRegistry
```

From README:

> "RACT keeps the human in the loop while a small management LM routes work to the
> right provider. Every plan and every result is `Rooted[T]` — it carries the
> assumption, confidence, and provenance that justify it."

## Root Knot continuity guard

Every non-init Python file carries:

```python
__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
```

> "If the recursion loop ever produces an artifact without the knot, the loop stops
> immediately rather than compounding unsigned work."

Contrast TeamShared: no code-output sentinel; session distillation captures
*conversation* truth, not *generated file identity* invariants.

## Anti-rot CLI arsenal

| Verb | Role |
|------|------|
| `rootact consolidate --dry-run` | Near-duplicate module merge preview |
| `rootact novelty scan` | Compression-based similarity; block near-duplicates |
| `rootact auction list` | Dead-code candidates by reachability |
| `rootact fence inspect --file` | "Chesterton's Fence" — why legacy code exists |
| `rootact whisper --intent` | Pre-plan dialect/history brief |
| `rootact coverage delta` | Fail on coverage regression |
| `rootact mutation run` | Local mutation testing (heavy diagnostic) |

Overlap with mex: both fight **rot** — mex on *instruction scaffold drift*,
RACT on *code duplication, dead code, undocumented load-bearing logic*.

## MCP and retrieval

RACT is an **MCP consumer**, not a memory server:

```yaml
# rootact.yaml
mcp_servers: [...]
```

> "`rootact mcp list` — Inspect tools exposed by configured MCP servers."

`RetrievalAdapter` provides keyword retrieval + web-search placeholder to augment
the Manager prompt — local, not org-scoped vector recall.

TeamShared could be configured as an `mcp_servers` entry for org recall during
RACT plan steps (`tool_call` steps via `McpToolRegistry`).

## Skills

Built-in signed skill templates (`python-package`, `fastapi-app`, `react-component`,
`test-generation`, `documentation-update`, `cli-tool`, `library-refactor`) plus a
**skill marketplace** (JSON templates in-repo).

Overlap TeamShared: `memory_skill_set` / `memory_playbook_set` are org-wide versioned
pillars; RACT skills are project-local installable templates.

## Signed receipts

```bash
rootact report --last --format json --output report.json
```

Captures intent, model, steps, test results, quality score, cost, latency, decision.
Positioned as cross-provider quality leaderboard substrate.

TeamShared: episodic events + audit logs + session distillation — different audit
shape (org timeline vs per-run engineering receipt).

## Provider model

Model-agnostic router: local HTTP, OpenAI, Anthropic, Z.ai, Moonshot, OpenRouter.
`CapabilityRegistry` scores providers by hint. Pay-only-for-tokens-you-route vs
Cursor/Claude Code subscription framing.

## Architecture highlights (docs/ARCHITECTURE.md)

- `Rooted[T]` — assumption-driven results with confidence/provenance
- `LoopController` / `ProgressOracle` — milestone-driven recursion (not time-based turns)
- `HandshakeRegistry` — async operator review for high-risk milestones
- `DiffApplier` — surgical unified-diff application with rollback
- `TokenBudget` — ranks context files by relevance
- 685 tests, 93% coverage (vendor claim, Jul 2026)
- Explicit **separation from Kairos** proprietary system (`docs/SEPARATION.md`)

## Competitive table (from README)

RACT claims wins on: pricing (local free + token routing), provider lock-in,
Progress Oracle loop, Root Knot continuity, anti-rot tooling, earned quality gates,
Operator Handshake async review, signed receipts, CLI-first sovereignty, surgical
diffs, local data option.

Cursor/Claude Code wins on: IDE integration, inline approval UX.

## Landscape placement (TeamShared taxonomy)

**Tier 3 — adjacent agentic coding harness** (competes with Cursor/Claude Code
*surface*, not GBrain/Cognee *memory budget*). Closest corpus neighbors:

| Peer | Overlap axis |
|------|----------------|
| mex | Anti-rot / hygiene (docs vs code) |
| Cursor + TeamShared plugin | Harness + MCP memory (RACT bundles both in one CLI) |
| GBrain skills | Project skills vs org skills |

Not Tier 1 company brain. Potential **complement**: RACT harness + TeamShared MCP
for org recall across repos.

## License / adoption signals

- PolyForm Noncommercial 1.0.0 — commercial license required for business use
- ~3 GitHub stars, 0 forks (Jul 2026) — very early
- Hugging Face demo space linked
- CLA required for contributions

## Open gaps (from public docs)

- Real-world multi-file loop validation still tuning Progress Oracle thresholds
- Use-case catalog expansion (`rootact_use_cases.jsonl`)
- No published integration story with cloud memory brains
