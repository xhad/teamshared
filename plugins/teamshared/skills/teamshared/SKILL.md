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
   still be true next week.
4. For work spanning ~3+ turns: `memory_session_open` → append turns →
   `memory_session_close(distill=true)`.
5. For repeatable playbooks: `memory_procedure_set` / `memory_procedure_get`.

## Tool chooser

| Need | Tool |
|---|---|
| Search all pillars | `memory_recall` |
| Store preference/fact/event/note | `memory_remember` |
| Multi-turn buffer + distillation | `memory_session_*` |
| Versioned how-to | `memory_procedure_set` |
| Browse timeline | `memory_episodes_list` |
| Explicit relationships (Neo4j on) | `memory_graph_*` |

Bearer token sets write attribution; durable reads are shared across agents
unless you pass `agent=` to narrow recall.
