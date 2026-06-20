# teamshared Memory Protocol

<!-- teamshared-rule-version: 1.4.0 -->

The `teamshared` MCP server is your durable brain across sessions and repos.
Bearer token sets write attribution; do not pass `agent` unless you intentionally
override it or narrow a read filter.

## Staying current

This rule is versioned (`version: 1.4.0` in the paired `teamshared.mdc`
frontmatter). The server ships the canonical rule and its version. Keep the
installed copy fresh:

1. On the **first turn of a chat** (or when the user asks about teamshared
   versions), call the `version` tool with this rule's version (`1.4.0`) as
   `installed_rule_version`. Do not call `version` every turn.
2. If the response has `update_available: true`, write the returned
   `rule_markdown` verbatim to your rule file (Cursor desktop:
   `~/.cursor/rules/teamshared.mdc`; repo / Cloud Agents:
   `.cursor/rules/teamshared.mdc`), then tell the user the memory rule was
   updated to the new version.
3. If `update_available: false`, do nothing — you're current.

Never invent a version; read it from the frontmatter or the `version` tool.

## Every turn checklist

Run these in order on **every** turn (see **Session logging** for setup details):

1. **Ensure session** — recover or open `session_id` (do not open a second
   session if `conversation/active-session` already has one for this chat).
2. **`memory_session_append(session_id, "user", ...)`** — the substantive user
   request (not boilerplate system context).
3. **`memory_recall(...)` or `memory_think(...)`** — one, not both, for
   non-trivial tasks (architecture, debugging, past work, "how do we…"). Skip
   for pure one-liner acknowledgments.
4. **Do the work** — tools, edits, answers.
5. **`memory_session_append(session_id, "assistant", ...)`** — a faithful summary
   of your reply. This should be your **last MCP call** before ending the turn.
6. **`memory_remember` / `work_*` / `memory_skill_set` / `memory_playbook_set`**
   — as needed for durable facts, tasks, atomic how-tos, or composed flows.

After significant tool use, optionally append a one-line `tool` turn summarizing
what ran and the outcome. Server middleware also logs MCP tool calls to a
separate autosession; your explicit session holds the NL story.

## Core workflows

### Recall first

Before any non-trivial request, call `memory_recall` (raw ranked records) or
`memory_think` (synthesized answer + citations + gaps) with the user's query
(step 3 above) — pick one, not both. Ground answers in hits; cite them.

- Omit `scope` to search all pillars (default).
- `scope=["procedural"]` / `scope=["skill"]` for "how do we usually…" (playbooks
  vs atomic skills).
- `scope=["strategic"]` for vision, mission, OKRs, and initiatives.
- `scope=["work"]` for open tasks, blockers, and assignee-owned work.
- `scope=["episodic"]` for "what did we do on X?".
- `scope=["semantic"]` for stable facts and preferences.
- `scope=["working"]` only when you need the caller's open session turns.
- `memory_recall(..., explain=true)` for attribution on each hit.
- For code/repo-specific work, pass `repo=<workspace-slug>` and/or
  `github=<owner>/<repo>` to softly boost scoped memories (nothing is hidden).

If recall is empty, say so before answering from priors.

### Assemble context

`memory_assemble_context(task=..., token_budget=...)` returns one token-budgeted
pack mixing recall + open work + relevant skills/playbooks for a task. Reach for
it when you want a single grounded starting context instead of hand-picking
scopes.

### Code work: resolve `repo` and `github`

**Always** resolve `repo=` for session logging, state, and code-scoped memory —
every chat, not only git tasks:

1. **Workspace slug** — run `git rev-parse --show-toplevel` when in a git
   checkout; otherwise use the Cursor workspace root. strip leading `/`,
   replace `/` with `-`. Pass as `repo=` on `memory_recall`, `memory_remember`,
   `memory_session_*`, and `memory_state_*`.
2. **GitHub repo** — when `command -v gh` succeeds, run
   `gh repo view --json nameWithOwner` from the repo root and pass
   `github=<nameWithOwner>` (e.g. `sapien/teamshared`). Stable across machines;
   the server stores `github:<owner>/<repo>`. Optional `subject=<nameWithOwner>`.
3. **Never** use `owner/repo` as `repo=` (slashes are invalid for workspace slugs).
4. If an MCP call fails with invalid JSON mentioning `repo`, omit `repo` and use
   `github=` (and/or explicit `tags`) instead; retry.

### Remember durable things

Call `memory_remember(content, kind=...)` for things still true next week:

| Signal | `kind` |
|---|---|
| "I prefer / always / never …" | `preference` |
| Stable repo fact | `fact` |
| One-off event worth logging | `event` |
| Misc working note | `note` |

Optional: `subject`, `tags`. `[[Entity]]` wikilinks autolink on write. For
code/repo-specific memories, pass `repo=<workspace-slug>` and/or
`github=<owner>/<repo>`; omit both for cross-cutting preferences. Do **not** use
`memory_remember` for skills or playbooks — use `memory_skill_set` /
`memory_playbook_set`.

### Skills vs playbooks

| Want | Tool |
|---|---|
| Atomic how-to (one task, one page) | `memory_skill_set` |
| Composed flow that wires skills together | `memory_playbook_set` + `tool_recipe.skills` |
| Agent loop with stages / auto-advance | `workflow_define` + `workflow_start` |

`memory_skill_set(name, body_md, tags=..., version=...)` stores a new versioned
skill. `memory_skill_get` / `memory_skills_list` read them. `memory_skill_resolve`
inlines the skill bodies a playbook references.

`memory_playbook_set(name, steps_md, tool_recipe={"skills": [...]})` stores a
composed playbook (alias: `memory_procedure_set`). `memory_playbook_get`
(`memory_procedure_get`) and `memory_playbooks_list` (`memory_procedures_list`)
read them. Rituals are skills; composed flows are playbooks. Never store an
atomic instruction as a playbook.

### Work queue (tasks for humans and agents)

Use `work_*` for durable, assignable tasks — not `memory_remember`.

1. **Start of task:** `work_list(mine=true)` or `work_list(work_status="todo")`
   to pick up existing work; otherwise `work_create(title=..., work_status="todo")`.
2. **Assign:** `assignee_agent="cursor"` or `assignee_email="teammate@..."` on
   create/update. Humans and agents are first-class assignees.
3. **Progress:** `work_update(work_id=..., work_status="in_progress")` — no
   re-approval. Use `work_status="blocked"` with `blocked_reason=` when stuck.
4. **Progress notes:** `work_comment_add(work_id=..., body=...)` for handoffs and
   blockers — not `memory_remember`.
5. **Finish:** `work_close(work_id=..., work_status="done")` when complete.
   Closing writes an episodic event for the timeline.

Work items are created active immediately for both humans and agents — task
creation does not go through the approval queue. Optional `initiative_id=`
links a task to a strategic initiative.

### Session logging (every chat)

Log conversation turns to teamshared on **every** chat via MCP — the agent owns
capture; there is no client-side transcript hook. Session logging via
`memory_session_*` is agent-initiated and does **not** use the `/sessions/turns`
consent path (unlike automatic transcript ingest).

Always resolve `repo=` first (see above). State key: `conversation/active-session`.
Treat a missing or empty `session_id` in state as no active session.

**First turn of a thread** (no prior assistant turns in your context):

1. `memory_state_get(repo=..., key="conversation/active-session")`.
2. If `session_id` is present → `memory_session_close(session_id, distill=true)`.
3. `memory_session_open(topic=<first user message, max ~120 chars>, repo=..., github=...)`.
4. `memory_state_set(repo=..., key="conversation/active-session", value={"session_id": "<id>"})`.

Do **not** call `memory_session_open` if state already holds a `session_id` for
this chat.

**Mid-thread pivot** (user clearly starts a new topic — do not wait for a new
Cursor chat):

1. `memory_session_close(session_id, distill=true)`.
2. `memory_state_set(..., value={})`.
3. Immediately `memory_session_open` with the new topic and update state — same turn.

**When done** (task complete, user says goodbye):

1. `memory_session_close(session_id, distill=true)`.
2. `memory_state_set(..., value={})`.

**Append failure recovery** — if `memory_session_append` fails (expired or
unknown `session_id`): open a new session, update state, retry the append once.

Append the substantive user request and a faithful summary of your reply — not
UI boilerplate. Truncate long tool output. Never append secrets, tokens, or
credentials.

### Entity hub

`memory_entity_view(slug=...)` returns one rollup for an entity: its wiki page,
related memories, graph neighbors, and open work. Use it when the user asks about
a specific subject (person, project, repo, concept) rather than running four
separate searches.

### Read vs write scoping

- **Shared brain (default):** `memory_recall` and `memory_episodes_list` return
  every agent's durable memories unless you pass `agent=` to narrow.
- **Caller-scoped working memory:** recall always includes the caller's own
  session turns; durable pillars are not filtered by caller unless `agent=` is set.
- **Writes:** `memory_remember`, `memory_session_*`, `memory_skill_set`,
  `memory_playbook_set`, and `memory_graph_relate` attribute to the bearer token
  unless `agent=` overrides. Guarded writes land **active** immediately; hard
  secrets are rejected.

## Human console (`/app`)

teamshared has a web console for humans at `<server>/app`
(e.g. https://teamshared.com/app). When a teammate asks how to *see* the
memory, sign in, get an API key, onboard, or manage their team, point them there —
these are human/browser actions, not MCP tools:

- **Sign in:** any email + a one-time passcode (no password). First sign-in
  creates that email's own private org; they can create more orgs and switch
  between them from the header.
- **Memory wiki** (`/app/wiki`): semantic facts, the episodic timeline, and
  playbooks rendered as a browsable, human-readable knowledge base.
- **Work** (`/app/work`): org-wide task queue; assign to people or agents.
- **Manage:** agents, **API keys** (`tsk_…`, the bearer token MCP/agents use),
  people (add a teammate by email), approvals, and capture consent (for automatic
  `/sessions/turns` ingest — not for agent-driven `memory_session_*` logging).

A fresh self-serve org starts empty and isolated; joining the shared team brain
is an admin action (People → add member). The public, no-auth status page is at
`<server>/memory`.

## Tool reference

Prefer the **Quick chooser** during tasks; use these tables when you need param
detail. Full catalog: `memory_tools_catalog(scope="memory", tier="core")`.

### `health`

Probe server liveness and dependencies. Returns
`{"status": "ok"|"degraded", "components": {...}}` covering redis, postgres, and
the memory/LLM backends (semantic, distiller, curator, graph, provider).
Use when MCP seems broken or before blaming empty recall on missing data.
Never run shell commands to inspect `TEAMSHARED_URL` / `TEAMSHARED_TOKEN` env
vars — MCP is configured inline in the client config, not the agent shell. If
MCP looks down, call `health`, not `echo`.

### `version`

Report the server version and the canonical rule version, and check whether the
installed rule is current.

| Param | Use |
|---|---|
| `installed_rule_version` | The `version` from this rule's frontmatter (optional; omit if unknown) |

Returns `{server_version, rule_version, installed_rule_version, rule_path,
update_available}` and, when `update_available` is true, the full `rule_markdown`
to write to the local rule file. See **Staying current** above.

### `memory_recall`

Hybrid search across semantic, episodic, procedural, skill, strategic, work, and
working pillars.

| Param | Use |
|---|---|
| `query` | Natural-language search (required) |
| `scope` | Subset of pillars; omit = all (includes work) |
| `k` | Max records (1–50, default 8) |
| `time_range` | Optional bounds for episodic/working hits |
| `agent` | Optional filter to one agent's durable writes |
| `repo` | Optional workspace slug; soft-boosts `repo:<slug>` tags (nothing hidden) |
| `github` | Optional `owner/repo`; soft-boosts `github:<owner>/<repo>` tags |
| `explain` | `true` to include attribution per hit |

Returns `records` with pillar, agent, timestamps, and content for citation.
For code work, pass `repo=<workspace-slug>` and/or `github=<owner>/<repo>`.

### `memory_think`

Synthesized answer with citations and gap analysis (use `memory_recall` for raw
records). Same params as `memory_recall`. Returns a grounded answer plus the
records it drew from and what's missing. Pick one of `memory_think` /
`memory_recall` per turn — not both.

### `memory_assemble_context`

One token-budgeted context pack for a task (recall + open work + relevant
skills/playbooks).

| Param | Use |
|---|---|
| `task` | The task description (required) |
| `token_budget` | Soft cap on returned context size |

### `memory_remember`

Write semantic or episodic memory.

| Param | Use |
|---|---|
| `content` | Text to store (required) |
| `kind` | `fact` \| `preference` \| `event` \| `note` (default `note`) |
| `subject` | Optional entity the memory is about |
| `tags` | Optional string list |
| `agent` | Optional attribution override |
| `repo` | Optional workspace slug → `repo:<slug>` tag |
| `github` | Optional `owner/repo` → `github:<owner>/<repo>` tag (portable) |

Routing: `event` → episodic; others → semantic. Rejects `kind=procedure`.
For code work, pass `repo=` and/or `github=`; omit both for cross-cutting facts.

### `memory_session_open` / `memory_session_append` / `memory_session_close` / `memory_session_get`

Working-memory buffer in Redis — one session per chat (see **Session logging**).

| Tool | Key params |
|---|---|
| `memory_session_open` | `topic`, optional `ttl`, `agent`, `repo`, `github` → `{session_id, agent}` |
| `memory_session_append` | `session_id`, `role` (`user` \| `assistant` \| `tool` \| `system`), `content` → `{turn_count}` |
| `memory_session_close` | `session_id`, `distill=true` (default) queues distillation to durable memory |
| `memory_session_get` | `session_id` → current turns/metadata |

### `memory_state_get` / `memory_state_set`

Token+repo scoped JSON blobs for client bookkeeping (not durable team knowledge).

| Param | Use |
|---|---|
| `repo` | Workspace slug: absolute path, leading `/` removed, `/` → `-` |
| `key` | Opaque key, e.g. `conversation/active-session`, `continual-learning/index` |
| `value` | JSON object (`memory_state_set` only); `{}` clears active session |

Prefer server state over git for incremental indexes and cadence files when MCP
is available; fall back to `~/.cursor/hooks/state/...` locally.

### `memory_episodes_list`

Browse the episodic timeline (distilled sessions and logged events).

| Param | Use |
|---|---|
| `topic` | Substring match |
| `since` / `until` | Time bounds on `created_at` |
| `limit` | 1–200 (default 20) |
| `agent` | Optional filter to one agent's episodes |

Default: all agents' episodes (shared brain).

### Skills: `memory_skill_get` / `memory_skill_set` / `memory_skills_list` / `memory_skill_resolve`

Versioned atomic how-tos in Postgres. Each `memory_skill_set` creates a new
version.

| Tool | When |
|---|---|
| `memory_skill_set` | Store new skill version: `name`, `body_md`, optional `tags`, `version` |
| `memory_skill_get` | Fetch by `name`, optional `version` (latest if omitted) |
| `memory_skills_list` | Discover skills; optional `tag`, `limit`, `offset` |
| `memory_skill_resolve` | Inline the skill bodies a playbook references |

### Playbooks: `memory_playbook_get` / `memory_playbook_set` / `memory_playbooks_list`

Versioned composed flows. Aliases: `memory_procedure_get` / `memory_procedure_set`
/ `memory_procedures_list`.

| Tool | When |
|---|---|
| `memory_playbook_set` | Store new version: `name`, `steps_md`, optional `description`, `tool_recipe`, `tags` |
| `memory_playbook_get` | Fetch by `name`, optional `version`, optional `expand_skills=true` to inline |
| `memory_playbooks_list` | Discover playbooks; optional `tag`, `limit`; `include_body=true` for full text |

`tool_recipe.shapes.skills_compose` loops through skill building blocks;
`workflow_stages` defines a multi-stage workflow graph (see `workflow_*`).

### `memory_entity_view`

Entity hub rollup.

| Param | Use |
|---|---|
| `slug` | Entity slug, e.g. `teamshared`, `alice`, `owner/repo` (required) |

Returns wiki page + related memories + graph neighbors + open work in one call.

### `memory_strategic_*`

Org-wide vision, mission, purpose, and OKR cycles. **Never** use
`memory_remember` for strategic content — use these tools instead.

| Tool | When |
|---|---|
| `memory_strategic_statement_get` | Active vision, mission, or purpose |
| `memory_strategic_statement_set` | Propose a new statement version |
| `memory_strategic_plan_list` / `memory_strategic_plan_get` | Browse OKR cycles |
| `memory_strategic_plan_set` | Propose a new cycle |
| `memory_strategic_objective_set` | Propose an objective |
| `memory_strategic_key_result_set` | Propose a key result |
| `memory_strategic_initiative_set` | Propose an initiative |

All strategic writes return `pending_approval` until a human approves them
in the console (`/app/approvals`).

### `work_list` / `work_get` / `work_create` / `work_update` / `work_close` / `work_comment_*`

Org-scoped task queue. Assign to **users** (`assignee_email` / `assignee_type=user`)
or **agents** (`assignee_agent` / `assignee_type=agent`).

| Tool | When |
|---|---|
| `work_list` | Table backlog; `mine=true`; filter `work_status`; `exclude_closed` (default true); `sort` |
| `work_get` | One item by `work_id` |
| `work_create` | New task; agent writes → active immediately |
| `work_update` | Status, assignee, priority, `blocked_reason` — immediate |
| `work_close` | `work_status=done` or `cancelled`; writes episodic timeline event |
| `work_comment_add` | Progress note on a task |
| `work_comment_list` | Thread on a task (oldest first) |

Workflow statuses: `backlog`, `todo`, `in_progress`, `blocked`, `done`, `cancelled`.
Do **not** store tasks via `memory_remember`. Use comments for progress, not facts.

### `memory_graph_relate` / `memory_graph_related`

Explicit entity relationships (Neo4j when enabled; otherwise no-op with
`reason: graph_disabled`).

| Tool | Use |
|---|---|
| `memory_graph_relate` | `subject`, `predicate`, `object`, optional `weight`, optional `agent` |
| `memory_graph_related` | Expand neighbors of `name`, `depth` (1–4), `limit` |

Use for structured facts vector recall would obscure (e.g. `alice` → `works_on` → `teamshared`).

### `memory_forget`

Soft-delete a semantic/episodic memory by `memory_id` (from a prior recall).
Requires `reason` for audit. **Only when the user explicitly asks.**

## Quick chooser

| Need | Tool |
|---|---|
| Is the server healthy? | `health` |
| Server/rule version + update check | `version` |
| Search all memory (raw records) | `memory_recall` |
| Synthesized answer + gaps | `memory_think` |
| One context pack for a task | `memory_assemble_context` |
| Store preference/fact/event/note | `memory_remember` |
| Log every chat + distillation | `memory_session_*` |
| Client incremental state | `memory_state_get` / `memory_state_set` |
| Browse timeline | `memory_episodes_list` |
| Atomic how-to | `memory_skill_set` / `memory_skill_get` |
| Resolve skills a playbook uses | `memory_skill_resolve` |
| Composed flow | `memory_playbook_set` / `memory_playbook_get` |
| List playbooks | `memory_playbooks_list` |
| Agent loop with stages | `workflow_*` |
| Entity hub (wiki + memories + graph + work) | `memory_entity_view` |
| Vision / OKRs / mission | `memory_strategic_*` or `scope=["strategic"]` |
| Tasks / assignees / blockers | `work_*` or `scope=["work"]` |
| Task progress notes | `work_comment_add` / `work_comment_list` |
| Structured relationships | `memory_graph_*` |
| Remove a bad memory | `memory_forget` (user-requested only) |

## Never

- Don't call `memory_forget` without explicit user instruction.
- Don't echo raw memory IDs unless the user asks.
- Don't fabricate hits — if `memory_recall` is empty, say so.
- Don't store secrets, tokens, or credentials in any memory tool.
- Don't open a second `memory_session_open` when state already has a `session_id` for this chat.
- Don't store atomic instructions as playbooks (use `memory_skill_set`).
- Don't probe `TEAMSHARED_*` env vars in shell — call `health`.
