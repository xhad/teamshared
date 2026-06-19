---
description: Use the teamshared MCP server as persistent cross-session memory.
alwaysApply: true
version: 1.5.0
---

# teamshared Memory Protocol

<!-- teamshared-rule-version: 1.5.0 -->

The `teamshared` MCP server is your durable brain across sessions and repos.
Bearer token sets write attribution; do not pass `agent` unless you intentionally
override it or narrow a read filter.

## Staying current

This rule is versioned (`version` in the frontmatter above, currently `1.5.0`).
The server ships the canonical rule and its version. Keep the installed copy
fresh:

1. On the **first turn of a chat** (or when the user asks about teamshared
   versions), call the `version` tool with this rule's frontmatter `version`
   (`1.5.0`) as `installed_rule_version`. Do not call `version` every turn.
2. If the response has `update_available: true`, write the returned
   `rule_markdown` verbatim to your rule file (Cursor desktop:
   `~/.cursor/rules/teamshared.mdc`; repo / Cloud Agents:
   `.cursor/rules/teamshared.mdc`), then tell the user the memory rule was
   updated to the new version.
3. If `update_available: false`, do nothing — you're current.

Never invent a version; read it from the frontmatter or the `version` tool.

## Every turn checklist

Tier by turn type — do not run the full stack on trivial acks (ok, yes, commit/push
only, lint fixes with no architecture questions).

**Always (every substantive turn):**

1. **Ensure session** — recover `session_id` from
   `memory_state_get(repo=..., key="conversation/active-session")`; open only on
   first turn or pivot (see **Session logging**). Never open a second session when
   state already has one for this chat.
2. **`memory_session_append(session_id, "user", ...)`** — substantive user request
   (not boilerplate system context).
3. **Do the work** — tools, edits, answers.
4. **`memory_session_append(session_id, "assistant", ...)`** — faithful summary of
   your reply. Should be your **last MCP call** before ending the turn.

**Normal task turns** (add between steps 2 and 3):

- **`memory_recall(...)`** or **`memory_think(...)`** — see **Recall first**;
  pick one, not both by default.

**Lifecycle turns:**

- **First turn of a new Cursor chat** — full session open flow (Session logging).
- **Mid-thread pivot** — close + distill + new session same turn.
- **Task done / goodbye** — `memory_session_close(distill=true)` + clear state.

**As needed:** `memory_remember` / `work_*`. After heavy tool use, optional one-line
`tool` turn. Server middleware also logs MCP tool calls to a separate autosession.

## Skills vs playbooks

| You have | Store with | Fetch with |
|---|---|---|
| Atomic instruction (`SKILL.md` block) | `memory_skill_set` | `memory_skill_get` / `scope=["skill"]` |
| Orchestration composing skills | `memory_playbook_set` + `tool_recipe.skills` | `memory_playbook_get` (`expand_skills=true`) |
| Multi-stage agent loop | `workflow_define` / `workflow_start` + `tool_recipe.stages` | `workflow_status` |

Bundled rituals (`teamshared.start-of-task`, etc.) are **skills**, not playbooks.

## Core workflows

### Recall first

Before non-trivial work, search team memory (step 3 above). Ground answers in
hits; cite them. If recall is empty, say so before answering from priors.

**Answer vs search:**

- **`memory_think(query=...)`** — synthesized prose answer with citations and gap
  analysis. Prefer when the user wants an **answer**.
- **`memory_recall(query=...)`** — raw ranked records. Use for IDs, debugging
  retrieval, or when you need to inspect sources yourself. Pass `explain=true` for
  vector/keyword/RRF attribution in each record's `metadata`.

**Scope hints** (default omits `scope` → all pillars below):

- `scope=["skill"]` — how-to building blocks ("how do we ship a PR?").
- `scope=["procedural"]` — playbooks and workflow definitions only.
- `scope=["strategic"]` — vision, mission, OKRs, initiatives.
- `scope=["work"]` — open tasks, blockers, assignees.
- `scope=["episodic"]` — "what did we do on X?".
- `scope=["semantic"]` — stable facts and preferences.
- `scope=["working"]` — caller's open session turns only.

Default pillars: `semantic`, `episodic`, `procedural`, `skill`, `strategic`,
`work`, `working`.

For code/repo work, pass `repo=<workspace-slug>` and/or `github=<owner>/<repo>`
to softly boost scoped memories (nothing is hidden).

Param detail for any tool: `memory_tools_catalog(scope="memory", tier="core")`.

### Code work: resolve `repo` and `github`

**Always** resolve `repo=` for session logging, state, and code-scoped memory —
every chat, not only git tasks:

1. **Workspace slug** — run `git rev-parse --show-toplevel` when in a git
   checkout; otherwise use the Cursor workspace root. Strip a leading `/`,
   replace `/` with `-`. Pass as `repo=` on `memory_recall`, `memory_remember`,
   `memory_session_*`, and `memory_state_*`.
2. **GitHub repo** — when `command -v gh` succeeds, run
   `gh repo view --json nameWithOwner` from the repo root and pass
   `github=<nameWithOwner>` (e.g. `xhad/teamshared`). Stable across machines;
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

Optional: `subject`, `tags`. For code/repo-specific memories, pass
`repo=<workspace-slug>` and/or `github=<owner>/<repo>`; omit both for
cross-cutting preferences.

Do **not** use `memory_remember` for instructions:

- Atomic skill → `memory_skill_set`
- Playbook orchestration → `memory_playbook_set`
- Facts about decisions → `memory_remember(kind="fact")`

**Wikilinks** — `[[Entity Name]]` in `memory_remember` content auto-creates graph
`mentions` edges on active writes (zero-LLM autolink).

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

`work_create` is **active immediately** for humans and agents (no approval queue).
Optional `initiative_id=` links a task to a strategic initiative. Projects,
subtasks, dependencies: `memory_tools_catalog(scope="work")`.

### Session logging (every chat)

Log conversation turns to teamshared on **every** chat via MCP — the agent owns
capture; there is no client-side transcript hook. Session logging via
`memory_session_*` is agent-initiated and does **not** use the `/sessions/turns`
consent path (unlike automatic transcript ingest).

Always resolve `repo=` first (see above). State key: `conversation/active-session`.
Treat a missing or empty `session_id` in state as no active session.

**First turn of a new Cursor chat** (no prior assistant turns in your context):

1. `memory_state_get(repo=..., key="conversation/active-session")`.
2. If `session_id` is present → `memory_session_close(session_id, distill=true)`.
   (Stale state from a prior chat — close + distill is intentional.)
3. `memory_session_open(topic=<first user message, max ~120 chars>, repo=..., github=...)`.
4. `memory_state_set(repo=..., key="conversation/active-session", value={"session_id": "<id>"})`.

Do **not** call `memory_session_open` if state already holds a `session_id` for
this chat.

**Mid-thread pivot** (user clearly starts a new topic):

1. `memory_session_close(session_id, distill=true)`.
2. `memory_state_set(..., value={})`.
3. Immediately `memory_session_open` with the new topic and update state — same turn.

**When done** (task complete, user says goodbye):

1. `memory_session_close(session_id, distill=true)`.
2. `memory_state_set(..., value={})`.

**Append failure recovery** — if `memory_session_append` fails (expired or
unknown `session_id`): open a new session, update state, retry the append once.

Never append secrets, tokens, or credentials.

### Read vs write scoping

- **Shared brain (default):** `memory_recall` and `memory_episodes_list` return
  every agent's durable memories unless you pass `agent=` to narrow.
- **Caller-scoped working memory:** recall always includes the caller's own
  session turns; durable pillars are not filtered by caller unless `agent=` is set.
- **Writes:** `memory_remember`, `memory_session_*`, `memory_skill_set`,
  `memory_playbook_set`, and `memory_graph_relate` attribute to the bearer token
  unless `agent=` overrides.

### Approval matrix

| Write | Typical agent outcome | `/app/approvals`? |
|---|---|---|
| `memory_remember` | `active` | Only if quarantined |
| `memory_skill_set` / `memory_playbook_set` | `active` | Only if quarantined |
| `memory_strategic_*` | `pending_approval` | Yes — human approves |
| `work_create` | `active` | No |
| Connector/extraction source | `pending_approval` | Yes |

Check status: `memory_approval_status(memory_id=... | skill_id=... | procedure_id=...)`.

## Human console (`/app`)

teamshared has a web console for humans at `<server>/app`
(e.g. https://teamshared.com/app). When a teammate asks how to *see* the
memory, sign in, get an API key, onboard, or manage their team, point them there —
these are human/browser actions, not MCP tools:

- **Sign in:** any email + a one-time passcode (no password). First sign-in
  creates that email's own private org; they can create more orgs and switch
  between them from the header.
- **Memory wiki** (`/app/wiki`): semantic facts, episodic timeline, skills, and
  playbooks as a browsable knowledge base.
- **Work** (`/app/work`): org-wide task queue; assign to people or agents.
- **Manage:** agents, **API keys** (`tsk_…`, the bearer token MCP/agents use),
  people (add a teammate by email), approvals, and capture consent (for automatic
  `/sessions/turns` ingest — not for agent-driven `memory_session_*` logging).

A fresh self-serve org starts empty and isolated; joining the shared team brain
is an admin action (People → add member). The public, no-auth status page is at
`<server>/memory`.

## Core tool reference

Full catalog: `memory_tools_catalog`. Below: tools every session should know.

### `health` / `version`

`health` — liveness + dependencies (redis, postgres, semantic, distiller,
curator, graph, LLM). Never probe `TEAMSHARED_*` env vars in shell; MCP config
is inline in the client.

`version` — pass `installed_rule_version` from this rule's frontmatter on first
turn; apply returned `rule_markdown` when `update_available: true`.

### `memory_think`

Synthesized answer with citations and explicit gaps (stale, missing, contradicts,
low confidence). Params: `query`, optional `k`, `repo`, `github`, `token_budget`.
Falls back to retrieval-only prose when LLM is unavailable.

### `memory_recall`

Hybrid search. Params: `query`, `scope`, `k`, `time_range`, `agent`, `repo`,
`github`, `verbose`, `explain`. Shared brain on durable pillars; `agent=` narrows.

### `memory_remember`

`kind`: `fact` | `preference` | `event` | `note`. `event` → episodic; others →
semantic. Rejects `kind=procedure`. Wikilink autolink on active writes.

### `memory_assemble_context`

One token-budgeted context pack for a `task` — parallel recall + optional graph;
prefer over serial recall when bootstrapping a complex job.

### Sessions

`memory_session_open` → `memory_session_append` → `memory_session_close(distill=true)`.
`memory_session_get` for debug/handoff.

### Skills and playbooks

- **Skills:** `memory_skill_get`, `memory_skill_set`, `memory_skills_list`,
  `memory_forget_skill`
- **Playbooks:** `memory_playbook_get` / `memory_playbook_set` /
  `memory_playbooks_list`, `memory_forget_procedure`
- **Compose:** `memory_skill_resolve(playbook_name=...)` or
  `memory_playbook_get(expand_skills=true)`
- `tool_recipe` shapes: `memory_tools_catalog` → `tool_recipe_shapes`
- Each `memory_skill_set` / `memory_playbook_set` creates a **new version** (not upsert)

### Graph

`memory_graph_relate(subject, predicate, object_entity)` — explicit edges.
`memory_graph_related(name, depth=1–4)` — walk neighbors. Neo4j when enabled;
Postgres fallback when Neo4j is down. Autolink from `[[wikilinks]]` on remember.

### Strategic / work / extended

- Strategic: `memory_strategic_*` — never `memory_remember` for OKRs/vision.
- Work: `work_list`, `work_get`, `work_create`, `work_update`, `work_close`,
  `work_comment_*` — tasks active immediately.
- Extended (discover via catalog): `agent_run_*`, `workflow_*`, `project_*`,
  `work_move`, dependencies, followers.

### `memory_state_get` / `memory_state_set`

Token+repo scoped JSON blobs (`conversation/active-session`,
`continual-learning/index`). Prefer server state over `~/.cursor/hooks/state/...`.

### `memory_forget`

Soft-delete semantic/episodic by `memory_id`. **Only when the user explicitly asks.**

## Quick chooser

**Tiers:** `core` = every session; `extended` = writes/debug; `human` = workflows.
Call `memory_tools_catalog(scope="memory", tier="core")` when unsure.

| Need | Tool |
|---|---|
| Discover tools + `tool_recipe` shapes | `memory_tools_catalog` |
| Is the server healthy? | `health` |
| Server/rule version + update check | `version` |
| **Answer** from team memory | `memory_think` |
| **Search** raw records / debug retrieval | `memory_recall` (`explain=true`) |
| Token-budgeted context pack | `memory_assemble_context` |
| Store preference/fact/event/note | `memory_remember` |
| Log every chat + distillation | `memory_session_*` |
| Read session turns | `memory_session_get` |
| Check guarded-write approval status | `memory_approval_status` |
| Browse timeline | `memory_episodes_list` |
| Atomic skill (building block) | `memory_skill_get` / `memory_skill_set` |
| Playbook (orchestration) | `memory_playbook_get` / `memory_playbook_set` |
| Resolve playbook → skills | `memory_skill_resolve` |
| Vision / OKRs / mission | `memory_strategic_*` or `scope=["strategic"]` |
| Tasks / assignees / blockers | `work_*` or `scope=["work"]` |
| Task progress notes | `work_comment_add` / `work_comment_list` |
| Structured relationships | `memory_graph_*` |
| Client incremental state | `memory_state_get` / `memory_state_set` |
| Remove semantic/episodic memory | `memory_forget` |
| Retire playbook or skill | `memory_forget_procedure` / `memory_forget_skill` |
| Background agent on a task | `agent_run_create` |
| Multi-stage workflow loop | `workflow_start` / `workflow_advance` |

## Never

- Don't call `memory_forget` without explicit user instruction.
- Don't echo raw memory IDs unless the user asks.
- Don't fabricate hits — if `memory_recall` is empty, say so.
- Don't store secrets, tokens, or credentials in any memory tool.
- Don't open a second `memory_session_open` when state already has a `session_id` for this chat.
- Don't store atomic instructions as playbooks — use `memory_skill_set`.
