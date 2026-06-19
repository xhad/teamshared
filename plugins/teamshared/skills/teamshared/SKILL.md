---
name: teamshared
description: Use teamshared MCP memory tools — recall before answering, remember durable facts, and log every chat via session workflows.
---

# teamshared memory

Use when a task benefits from shared team memory, past decisions, or durable
preferences stored in teamshared.

## Workflow

Follow the **every turn checklist** in `teamshared.mdc`:

1. Ensure session (`conversation/active-session` in `memory_state`).
2. Append user turn → `memory_recall` (non-trivial) → work → append assistant turn.
3. `memory_remember(...)` for preferences, facts, events, and notes that should
   still be true next week. For code work: resolve workspace slug via
   `git rev-parse --show-toplevel` → `repo=`; resolve GitHub via
   `gh repo view --json nameWithOwner` when available → `github=`.
4. On pivot: close session, open new one, update state — same turn.
5. On append failure: reopen session, update state, retry once.
6. For repeatable playbooks: split atomic steps with `memory_skill_set`, compose
   orchestrators with `memory_playbook_set` + `tool_recipe.skills`, fetch with
   `memory_playbook_get(expand_skills=true)`.

## Tool chooser

| Need | Tool |
|---|---|
| Search all pillars | `memory_recall` |
| Store preference/fact/event/note | `memory_remember` |
| Store atomic skill (how-to block) | `memory_skill_set` |
| Store playbook orchestrator | `memory_playbook_set` |
| Log every chat + distillation | `memory_session_*` |
| Browse timeline | `memory_episodes_list` |
| Explicit relationships (Neo4j on) | `memory_graph_*` |
| Active session bookkeeping | `memory_state_get` / `memory_state_set` |

Bearer token sets write attribution; durable reads are shared across agents
unless you pass `agent=` to narrow recall.

## Human console

For human actions — signing in, browsing the memory wiki, minting API keys,
adding teammates, switching orgs — point people to the web console at
`<server>/app` (e.g. https://teamshared.com/app). Sign-in is self-service
(any email + one-time passcode); the first sign-in creates that email's own org.
Don't attempt these through MCP tools.
