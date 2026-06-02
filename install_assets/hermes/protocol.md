# teamshared Memory Protocol (copy-paste for Hermes, Claude, and other hosts)

Paste this block into the host's system prompt, project instructions, or
`CLAUDE.md`. MCP wiring alone does not make the model call memory tools reliably.

For **Hermes**, paste this section into `~/.hermes/SOUL.md` (loaded every message).
Hermes also has a local `memory` tool and MEMORY.md — those are not teamshared;
see the MEMORY.md vs teamshared table below.

---

The `teamshared` MCP server is your durable brain across sessions and repos.
Agent identity is resolved from the bearer token; do not pass `agent` on writes
unless you intentionally override attribution.

When the user says **"save to teamshared"**, **"remember this for the team"**, or
names teamshared as the destination, call `memory_remember` (or the matching
teamshared MCP tool). Do not write to MEMORY.md or the Hermes `memory` tool.

**Do not use `sessions_list` to decide whether teamshared is available.** That
tool lists local Hermes chat sessions only — teamshared never appears there.
MCP tools (`memory_remember`, `memory_recall`, …) live on the separate
`teamshared` MCP server wired in `~/.hermes/config.yaml`. If unsure, call
`health` on teamshared, then `memory_remember`.

| Store | Tool | Use for |
|-------|------|---------|
| MEMORY.md | Hermes `memory` | Local assistant notes only (~2.2k chars) |
| teamshared MCP | `memory_recall`, `memory_remember`, … | Shared team knowledge |

| User intent | Call |
|-------------|------|
| Save / remember for the team or teamshared | `memory_remember(content, kind=…)` |
| Search past work or team knowledge | `memory_recall(query)` |
| Multi-turn task buffer | `memory_session_open` / `_append` / `_close` |

## Recall first

Before answering any non-trivial request (architecture questions, debugging,
"how do I…", anything referencing past work), call `memory_recall` with the
user's query. Use the returned hits to ground your answer and cite them.

- Default `scope`: omit (searches all pillars).
- Narrow to `["procedural"]` when the user asks "how do we usually…".
- Narrow to `["episodic"]` when the user asks "what did we do on X?".

If recall returns nothing relevant, say so before answering from priors.

## Remember durable things

Call `memory_remember(content, kind=...)` when the user states something that
will still be true next week:

| Signal | `kind` |
|---|---|
| "I prefer / always / never …" | `preference` |
| Stable repo fact | `fact` |
| One-off event worth logging | `event` |
| Misc working note | `note` |

Use `memory_procedure_set` for versioned playbooks (not `memory_remember`).

## Sessions for multi-turn work

For tasks spanning more than ~3 turns:

1. `memory_session_open(topic=<short label>)`
2. `memory_session_append(session_id, role, content)` after each turn
3. `memory_session_close(session_id, distill=true)` when done or pivoting

## Never

- Don't call `memory_forget` without explicit user instruction.
- Don't fabricate hits — if `memory_recall` is empty, say so.
