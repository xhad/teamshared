# Changelog

## 0.7.0 — 2026-06-29

- **Rule 1.7.0:** retrieval playbook — durable default scope (exclude working),
  keyword-anchor-then-broaden queries, recall-before-think for entity/competitor
  questions, no `[tool]` appends for teamshared MCP calls, dense summary guidance
  on `memory_remember`.
- **Server:** `DEFAULT_RECALL_SCOPES` and `memory_think` default recall omit
  working; MCP tool descriptions and server instructions updated to match.
- **Installer:** Pi coding agent harness (`pi`) — project-local `./.mcp.json`.

## 0.6.0 — 2026-06-25

- **Rule 1.6.0:** removed the agent-execution surface — cloud/background agent
  runs (`agent_run_*`), the workflow engine (`workflow_*`), and agent assignees
  (`assignee_agent`). Work items assign to **people** only; API keys are
  org-bound and carry a free-text attribution label. Dropped all "Cloud Agents"
  references.

## 0.5.0 — 2026-06-19

- **Install consolidation:** all curl-install templates live under `install/` in
  this plugin bundle; repo-root `install_assets/` removed. Server resolves assets
  via `teamshared.clients.install_assets` (aliases: rule → `rules/`, protocol →
  `clients/protocol.md`).
- **Rule 1.5.0:** context compression via MCP (`context_prepare`, `context_normalize`,
  `context_compress`, `context_retrieve`); MCP middleware auto-normalizes teamshared
  tool responses; removed Cursor compression hooks (`beforeSubmitPrompt`, `postToolUse`).
- **Rule 1.5.0:** `memory_think` + recall `explain`; skills vs playbooks decision
  tree; tiered every-turn checklist; approval matrix; graph autolink + Postgres
  fallback; slim tool reference (delegate to `memory_tools_catalog`); fix
  `work_create` active-immediately guidance; bundled rituals documented as skills.

## 0.4.0 — 2026-06-08

- **Rule 1.3.0:** log every chat via `memory_session_*` (open on first turn,
  append user/assistant each round, close on done/pivot). State key:
  `conversation/active-session`.
- Removed the Cursor `conversation-capture-stop` transcript hook; NL capture is
  agent-driven through MCP instead of `POST /sessions/turns`.
- Continual-learning stop hook unchanged.
- **Rule 1.4.0:** every-turn checklist (ordered steps), mid-thread pivot handling,
  append-failure recovery, always resolve `repo=`, consent clarification, aligned
  starter procedures.

## 0.3.0 — 2026-06-01

- Rule + skill now point teammates to the **web console** (`/app`) for human
  actions: self-service OTP sign-in, multi-tenant orgs (own org on first login,
  create/switch, add members), the browsable memory wiki, and managing agents,
  API keys, approvals, and consent.
- Onboarding (README + MARKETPLACE) updated: mint a bearer token from the console
  **API Keys** page (self-service) in addition to `/get-token` / invite links.
- `health` tool description corrected to reflect the full component set.

## 0.2.0 — 2026-05-28

- Unified `teamshared-memory` and continual-learning into one **teamshared** plugin.
- Continual-learning hook stores cadence + transcript index on teamshared (`/state` API).
- MCP server key standardized to `teamshared`.
- Rule file renamed to `teamshared.mdc`.

## 0.1.0

- Initial `teamshared-memory` plugin: MCP wiring, recall-first rule, client snippets.
