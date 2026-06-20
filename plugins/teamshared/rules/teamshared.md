---
description: Use the teamshared MCP server as persistent cross-session memory.
alwaysApply: true
version: 1.6.1
---

# teamshared Memory Protocol

<!-- teamshared-rule-version: 1.6.1 -->

Bearer token sets write attribution. Pass `agent=` only to override identity or narrow reads.

## Staying current

Frontmatter `version` is canonical. **First turn only** (or when asked): `version(installed_rule_version="<version>")`. If `update_available`, write returned `rule_markdown` verbatim to `~/.cursor/rules/teamshared.mdc` or `.cursor/rules/teamshared.mdc` and tell the user. Never invent a version.

## Every turn

Skip the full stack on trivial acks (ok, yes, commit/push-only, lint-only).

**Substantive:** (1) ensure session — `memory_state_get(repo, "conversation/active-session")`; open only on first turn or pivot; never double-open; (2) `memory_session_append(user)`; (3) work; (4) `memory_session_append(assistant)` **last**.

**Before step 3:** `memory_recall` or `memory_think` — one, not both. **Lifecycle:** new chat → open flow below; pivot → close+distill+open; done → close+distill+clear state. Optional: `memory_remember`, `work_*`.

## Recall

Ground answers in hits; cite them; say if empty. **`memory_think`** — synthesized answer + gaps. **`memory_recall`** — raw ranked records; `explain=true` for attribution. Scopes: `semantic`, `episodic`, `procedural`, `skill`, `strategic`, `work`, `working`. Code work: pass `repo` and/or `github` (boost only). Params: `memory_tools_catalog(scope="memory", tier="core")`.

## repo + github

Resolve on **every** chat (not only git tasks):

1. **`repo=`** — git root path slug: strip leading `/`, replace `/` with `-`.
2. **`github=`** — `gh repo view --json nameWithOwner` → `owner/repo` tag.
3. Never use `owner/repo` as `repo=`. If MCP JSON errors on `repo`, retry with `github=` only.

Use on `memory_recall`, `memory_remember`, `memory_session_*`, `memory_state_*`.

## Remember & work

**`memory_remember`** — durable truths (`kind`: preference | fact | event | note). Not instructions, OKRs, or tasks. `[[Entity]]` wikilinks autolink on write.

**Skills vs playbooks:** atomic how-to → `memory_skill_set`; composed flow → `memory_playbook_set` + `tool_recipe.skills`; agent loop → `workflow_*`. Rituals are skills.

**`work_*`** — assignable tasks (active immediately): list → create/update → comment → close. Not `memory_remember`.

## Session logging

Agent-owned via `memory_session_*` (separate from the server-side `/sessions/turns` capture sink). State key: `conversation/active-session`.

**New chat:** state_get → if stale `session_id`, `memory_session_close(distill=true)` → `memory_session_open(topic≤120ch, repo, github)` → state_set. **Pivot:** close+distill, clear state, open. **Done:** close+distill, clear. Append failure → reopen session, retry once. No secrets.

## Scoping & writes

Reads: shared brain by default; `agent=` narrows durable pillars; working memory always caller-scoped. Writes attribute to bearer unless `agent=` override. Guarded writes land **`active`** immediately; hard secrets rejected.

## Tools

Full catalog: `memory_tools_catalog`. Session essentials: `health`, `version`, `memory_think`, `memory_recall`, `memory_remember`, `memory_assemble_context`, `memory_session_*`, `memory_state_*`, `memory_skill_set`, `memory_playbook_set`, `work_*`, `memory_graph_*`.

## Never

- `memory_forget` only when user explicitly asks.
- Don't fabricate recall hits or echo raw memory IDs unless asked.
- No secrets/tokens in any memory tool.
- No second `memory_session_open` when state already has a `session_id`.
- No atomic instructions as playbooks.
- Don't probe `TEAMSHARED_*` in shell — use `health`.
