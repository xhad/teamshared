# Changelog

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
