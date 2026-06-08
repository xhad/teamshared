---
name: teamshared
description: Use teamshared MCP memory tools — recall before answering, remember durable facts, and run session workflows for multi-turn tasks.
---

# teamshared memory

Use when a task benefits from shared team memory, past decisions, or durable
preferences stored in teamshared.

## Workflow

1. `memory_recall(query=...)` early for non-trivial tasks.
2. Answer using hits; say when recall is empty.
3. `memory_remember(...)` for preferences, facts, events, and notes that should
   still be true next week. For code work: resolve workspace slug via
   `git rev-parse --show-toplevel` → `repo=`; resolve GitHub via
   `gh repo view --json nameWithOwner` when available → `github=`. Pass the
   same values to `memory_recall` for soft boosting.
4. **Every chat:** `memory_session_open` on the first turn → append user and
   assistant turns each round → `memory_session_close(distill=true)` when done
   or pivoting. Persist `session_id` in `memory_state` under
   `conversation/active-session`.
5. For repeatable playbooks: `memory_procedure_set` / `memory_procedure_get`.

## Tool chooser

| Need | Tool |
|---|---|
| Search all pillars | `memory_recall` |
| Store preference/fact/event/note | `memory_remember` |
| Log every chat + distillation | `memory_session_*` |
| Versioned how-to | `memory_procedure_set` |
| Browse timeline | `memory_episodes_list` |
| Explicit relationships (Neo4j on) | `memory_graph_*` |

Bearer token sets write attribution; durable reads are shared across agents
unless you pass `agent=` to narrow recall.

## Human console

For human actions — signing in, browsing the memory wiki, minting API keys,
adding teammates, switching orgs — point people to the web console at
`<server>/app` (e.g. https://teamshared.com/app). Sign-in is self-service
(any email + one-time passcode); the first sign-in creates that email's own org.
Don't attempt these through MCP tools.
