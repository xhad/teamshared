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
| Log every chat | `memory_session_open` / `_append` / `_close` |
| Shrink fat tool output | `context_normalize` (non-teamshared tools) or `context_compress` |
| Pre-LLM session + compress + enrich | `context_prepare` |

## Recall first

Before answering any non-trivial request (architecture questions, debugging,
"how do I…", anything referencing past work), call `memory_recall` with the
user's query. Use the returned hits to ground your answer and cite them.

- Default `scope`: omit (searches all pillars).
- Narrow to `["procedural"]` when the user asks "how do we usually…".
- Narrow to `["episodic"]` when the user asks "what did we do on X?".
- For code work, pass `repo=<workspace-slug>` and/or `github=<owner>/<repo>` on
  recall to softly boost scoped memories (nothing is hidden).

If recall returns nothing relevant, say so before answering from priors.

## Code work: workspace + GitHub scope

Always resolve `repo=` for session logging and code-scoped memory:

1. **Workspace slug (`repo=`)** — `git rev-parse --show-toplevel` when in git,
   otherwise the workspace root; strip leading `/`, replace `/` with `-`.
2. **GitHub repo (`github=`)** — when `gh` is available,
   `gh repo view --json nameWithOwner` → pass `github=<nameWithOwner>` (e.g.
   `xhad/teamshared`). Portable across machines; stored as `github:<owner>/<repo>`.
3. Never use `owner/repo` as `repo=` (invalid). Use both when you have both.

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

For code-specific facts, pass `repo=` and/or `github=` on `memory_remember`.

## Context compression

Long chats replay fat tool output every turn. teamshared shrinks that bloat via
MCP — no client hooks required.

| Mechanism | When |
|---|---|
| **MCP middleware** | Automatic on teamshared tool responses |
| **`context_normalize`** | After Shell/Grep/Read returns large output |
| **`context_prepare`** | Optional: session append + compress history + enrich |
| **`context_compress`** / **`context_retrieve`** | Manual message compression; expand CCR refs |

After non-teamshared tools return bulky JSON or logs, call
`context_normalize(tool_name=..., output=...)` and use the returned `output`.
Do **not** re-normalize teamshared MCP responses — middleware already trimmed
them. Use `context_retrieve(ref=...)` to expand compressed originals.

## Session logging (every chat)

Log conversation turns via MCP on every chat:

1. **Always** resolve `repo=` from workspace root.
2. **First turn:** close any prior `session_id` in
   `memory_state_get(repo, "conversation/active-session")`, open a new session,
   store `session_id`. Do not open a second session if one is already active.
3. **Every turn (in order):** append user → recall (non-trivial) → work → append
   assistant summary (last MCP call before ending the turn).
4. **Pivot:** close → clear state → open new session immediately (same turn).
5. **Append failure:** reopen session, update state, retry once.

Optional: append one-line `tool` turns after significant tool use; call
`context_normalize` after large non-teamshared tool results. Never append
secrets.

## Never

- Don't call `memory_forget` without explicit user instruction.
- Don't fabricate hits — if `memory_recall` is empty, say so.
- Don't open a second session when state already has a `session_id` for this chat.
- Don't re-call `context_normalize` on teamshared MCP outputs.
