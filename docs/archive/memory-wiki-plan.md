# Memory Wiki + Capture — Design (historical)

> **Archived (2026-06):** the `/app` console and wiki curator shipped and are
> current. **The consent-first capture model described below was retired
> (2026-06-19)** — capture is now gated only by the `capture_enabled` setting,
> and the `consent_grants` table / `ConsentStore` / `/app/consent` UI were
> removed. This document is retained as a historical design artifact; do not
> implement anything from §6 (Consent-first capture) or the consent portions
> of later sections. See `README.md` and `AGENTS.md` for the current
> architecture.

Status: proposal / design (historical). Builds on `plan.md` (memory
architecture) and `prod-plan.md` (multi-tenant production stack). This
document originally captured the redesign of the teamshared **web app** and
the **capture → curate → wiki** knowledge pipeline, with a **consent-first**
governance model as a hard constraint. The consent-first constraint has since
been lifted — capture is flag-gated, not consent-gated.

---

## 1. Vision

One server-rendered web app — the **team mind** — where a human signs in to:

- **see the state** of the memory system at a glance,
- **browse the data** as a human-readable, continuously updating **wiki**, and
- **manage** the agents, users, and API keys that read/write it.

Agents keep talking to `/mcp`. Humans get a clean console at `/app`. The wiki is
fed by agent conversations, but **only data a human has explicitly approved and
the client has already sanitized** ever leaves the agent machine.

## 2. Decisions locked in

| Decision | Choice |
|---|---|
| Rendering | **Jinja2 + HTMX**, server-rendered, no Node/build step, pure Python endpoints |
| Identity model | **Production RLS/RBAC stack only** (`tsk_` API keys, users, agents, roles, orgs). Legacy `teamshared_` tokens/data are **out of scope** for the new app. |
| App location | **Public landing at `/`** + signed-in **console under `/app`** |
| `/admin` | **Removed**; its useful views fold into the console |
| Capture | **Consent-first, client-sanitized, push-only** (see §6) |

## 3. Architecture overview

```
                 ┌────────────────────────── agent machine (client) ──────────────────────────┐
 harness  ─────> │  hook: [1] local sanitize  ->  [2] human approval  ->  push only if approved │
                 └───────────────────────────────────┬──────────────────────────────────────────┘
                                                      │  POST /sessions/turns (+ consent ref)
                                                      ▼
  server (pure sink, never pulls) ── verify consent ── working buffer (Redis)
                                                      │ idle / rollover
                                                      ▼
                                              distill queue (Redis)
                                                      │
                                        DistillWorker.summarize() ── LLM ──> {episode, facts, decisions, relations}
                                                      │
                                  IngestionPipeline (sanitize backstop + dedup + PII + injection + approvals)
                                                      ▼
                             semantic + episodic memory (pgvector/RLS) + graph relations (Neo4j)
                                                      │ debounced per subject
                                                      ▼
                                       CuratorWorker ── LLM ──> synthesized markdown
                                                      ▼
                                   wiki_pages (versioned, sourced)  ──>  /app/wiki
```

Existing today: capture middleware + `/sessions/turns`, working buffer, distill
queue, `DistillWorker`, `summarize()`, `IngestionPipeline`, `ApprovalQueue`.
New: consent gate + client sanitizer, richer summarizer schema, `CuratorWorker`,
`wiki_pages`, `consent_grants`, optional `raw_transcripts`, and the console UI.

## 4. The web console

### Information architecture

```
/                      Public landing (kept simple) + "Sign in" / "Open console"
/login, /login/verify  Magic-link auth (reuse issue_session / verify_session)
/app                   Console home — team-mind overview (stats, health, recent activity)
/app/wiki              Wiki home: topic index, tag cloud, recently updated, search
/app/wiki/topic/{slug} Curated topic page (synthesized markdown + sources + backlinks)
/app/wiki/timeline     Episodic journal
/app/wiki/playbooks    Procedural docs + version history
/app/memory            Raw/atomic explorer (search + filter over records)
/app/memory/{id}       Single record permalink (edit / delete / share)
/app/agents            Agents: list + add + per-agent activity
/app/people            Users/members: list + invite + roles
/app/keys              API keys: list + mint + revoke
/app/approvals         Pending-memory review queue (approve / reject)
/app/consent           Capture & consent: per-agent scopes, sanitization profile, what's been shared, revoke
/app/audit             Audit timeline
/app/settings          Retention, connectors, org info, export/purge
```

### Screen → backend capability map

| Screen | Backed by (existing unless noted) |
|---|---|
| Console home | `working.stats`, `vector_store.pillar_stats`/`stats`, `procedural.stats`, `check_components`, `audit.list_events` |
| Wiki topic/timeline/playbooks | **new** `wiki_pages` + `vector_store.list_recent` + `procedural` + `graph.related` |
| Memory explorer / detail | `POST /v1/memory/search`, `GET/PATCH/DELETE /v1/memory/{id}`, `.../share` |
| Agents | `GET/POST /v1/agents` (+ **new** disable/delete) |
| People | `GET /v1/members`, `POST /v1/members/{id}/roles` (+ **new** invite, revoke role) |
| API keys | `GET/POST/DELETE /v1/api-keys` |
| Approvals | `GET /v1/approvals`, `POST /v1/approvals/{id}/decide` |
| Consent | **new** `consent_grants` CRUD + audit |
| Audit | `GET /v1/audit` |
| Settings | `/v1/retention-policies`, `/v1/connectors`, `/v1/admin/export`, `/v1/orgs/me` |

### Tech notes
- `Jinja2Templates` in `app.py`; `templates/base.html` (one stylesheet/header/nav),
  `templates/partials/*` for HTMX fragments.
- HTMX (single `<script>` tag) for live search, approve/revoke, key-reveal, inline forms.
- Jinja autoescaping replaces the hand-rolled `escape()` in the f-string pages.
- Console pages gated by the `ts_session` cookie; writes additionally checked via
  `Authorizer.require(...)` so the UI enforces the same RBAC as `/v1`.

## 5. The wiki: records → curated pages

Keep the write model as-is; add **read-only rendered views** plus a **curated,
materialized** layer.

| Pillar | Wiki shape | Rendering |
|---|---|---|
| Semantic (facts/prefs/notes; `subject` + `tags`) | Knowledge-base topic pages | One page per `subject`; sections by kind, newest first, with provenance |
| Episodic (distilled sessions/events; timestamped) | Timeline / devlog | Reverse-chronological dated entries |
| Procedural (versioned `steps_md`) | Docs + history | Render `steps_md`; version rows = page history |

**Curated topic page** = a `CuratorWorker` synthesizes all facts + recent episodes
+ relations for a subject into one canonical markdown article (dedupe, reconcile
contradictions by recency/confidence, drop noise, TOC), stored in `wiki_pages`
with `sources` (the contributing `memory_id`s) and a version. Superseded raw
facts are marked (supersede chain), never deleted. Neo4j relations power
cross-links + "what links here" backlinks.

**Continuously updating** = event-driven + debounced: when ≥N new facts land for a
subject, enqueue a recompaction; plus a scheduled full pass. Busy topics
re-render without thrashing on every turn.

## 6. Consent-first capture (hard constraint)

**No data is captured or pulled without explicit human approval, and the client
sanitizes it before it ever leaves the machine.**

### Principles
1. **Server never pulls.** It has no path to read a harness transcript; it only
   receives what a client explicitly pushes. Capture is **push-only**.
2. **Client sanitizes first.** Redaction runs in the harness hook *before*
   transmission. Server-side scrubbing is defense-in-depth only.
3. **Human approves before transmission** — interactively per batch, or via a
   policy the human pre-agreed to. No approval → nothing sent.
4. **Consent is recorded, audited, and revocable.**

### Client-side flow (the hook/adapter)
```
harness transcript
   -> [1] local sanitizer: redact secrets/PII (API keys, tokens, emails, paths;
          regex + high-entropy detection); mask or drop
   -> [2] human approval gate:
          • review mode: "Share these N turns to team memory? [view/redact/approve/deny]"
          • policy mode:  human pre-approved scope + redaction profile; hook enforces
   -> [3] POST /sessions/turns  (only approved + sanitized content + consent reference)
```

### Server-side enforcement
- `/sessions/turns` **requires a valid consent reference**; rejects + audits otherwise.
- The auto `ToolCallCaptureMiddleware` is **gated behind an active consent grant**
  and **defaults off** — it must not record silently.
- `IngestionPipeline` runs a **second** sanitization pass; `ApprovalQueue`
  (`memory:approve`) remains the sink-side human gate before durable/wiki.

### Required changes (the things that currently violate the principle)

| Today | Change |
|---|---|
| `ToolCallCaptureMiddleware` silently records every tool call (`capture_enabled` default `True`) | Gate behind a per-agent consent grant; **default off** without consent |
| `/sessions/turns` accepts any bearer-authed turns | Require + verify a consent reference; audit every accepted batch |
| Client hooks just forward turns | Add **client-side sanitizer + approval step** before sending (most important new code) |
| No consent record | New `consent_grants` table + audit events + `/app/consent` UI |

### Consent modes
1. **Review** — human approves each batch (max control).
2. **Policy** — human pre-approves a scope + redaction profile once; hook enforces.
3. **Off** — default; nothing captured.

## 7. Data-model additions (proposed migrations)

Migrations are numbered `NNN_name.sql` (next free is `011`). Proposed:

### `011_consent.sql` — `consent_grants`
| Column | Notes |
|---|---|
| `id uuid pk` | |
| `org_id uuid` | RLS tenant key |
| `principal_type text` / `principal_id uuid` | the agent/user the grant covers |
| `scope text[]` | e.g. `{tool_calls}`, `{distilled_facts_only}`, `{raw_turns}`, repo/project filters |
| `sanitization_profile jsonb` | redaction ruleset enforced client-side (baseline + overrides) |
| `mode text` | `review` \| `policy` \| `off` |
| `granted_by uuid` | the human who approved |
| `granted_at timestamptz`, `expires_at timestamptz null`, `revoked_at timestamptz null` | |

A capture request carries a reference resolving to an active (non-revoked,
non-expired) grant whose scope covers the payload.

### `012_wiki.sql` — `wiki_pages`
| Column | Notes |
|---|---|
| `id uuid pk`, `org_id uuid` | |
| `slug text` | canonical subject slug; unique per org |
| `title text`, `body_md text` | synthesized markdown |
| `version int` | versioned = free page history |
| `sources uuid[]` | contributing `memory_item` ids (provenance) |
| `updated_at timestamptz`, `updated_by text` | `curator` |

### `013_raw_transcripts.sql` — optional scrubbed archive
Durable, **already-sanitized** raw turns keyed by `session_id` for provenance and
reprocessing, separate from recall so it never pollutes search. Only written for
consent scopes that include `raw_turns`.

## 8. Client-side sanitizer spec

Ships with the harness adapters (Cursor/Hermes hooks today; extend to
Claude/Codex/OpenClaw). Runs **before** any network call.

- **Secret detection:** high-entropy strings; known token shapes (`tsk_`, `sk-`,
  `ghp_`, AWS keys, JWTs, private-key headers); `.env`-style `KEY=VALUE`.
- **PII:** emails, phone numbers, absolute home paths, IPs (configurable).
- **Action:** redact-in-place (`«redacted:secret»`) or drop the turn; never send raw.
- **Baseline is non-loosenable:** a human can tighten the profile but not below the
  shipped baseline.
- **Determinism + audit:** record what categories were redacted (counts, not
  values) so `/app/consent` can show a redaction summary.
- Server-side `IngestionPipeline` re-runs equivalent checks as a backstop.

## 9. Backend gaps to close (additive, test-first)

Per `AGENTS.md` ("add a test before extending the tool surface"):
1. Invite/create user — only `signup_org` exists today → `AdminService.invite_member` + `POST /v1/members`.
2. Revoke role — `RoleStore.unbind_role` + `DELETE /v1/members/{id}/roles/{role}`.
3. Disable/delete agent — `AdminService.set_agent_status` + `PATCH/DELETE /v1/agents/{id}`.
4. Retention update/delete.
5. Consent grant CRUD + capture-time verification.
6. Curator: `wiki_pages` store + `CuratorWorker` + curate queue.
7. Richer summarizer schema (`subject`, `tags`, `confidence`, `relations`).

## 10. Phased implementation

1. **Foundation** — add `jinja2`; `templates/` + `base.html`; session-gated `/app`
   shell + nav; **retire `/admin`** (routes/UI/tests); console home from existing stats.
2. **Consent-first capture** — `consent_grants` migration + store; gate the
   middleware (default off) and `/sessions/turns` on consent; client-side
   sanitizer + approval step in the hooks; `/app/consent` UI.
3. **Read the data** — memory explorer/detail, agents/people/keys/approvals/audit
   (read paths exist).
4. **Wiki** — richer summarizer schema; `wiki_pages` + `CuratorWorker`;
   `/app/wiki` topic/timeline/playbooks rendering (with sanitized markdown).
5. **Manage** — write actions + gap-closing endpoints (§9): add/disable agent,
   mint/revoke key, approve/reject, invite/grant/revoke role, retention.
6. **Polish** — HTMX niceties, empty states, mobile, refresh public landing +
   `/memory`, update `README.md` + `AGENTS.md`.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Secrets/PII in agent I/O | Client sanitize first + human approval; server backstop + approval queue; never archive unscrubbed |
| Silent capture violates consent | Middleware default off, gated on consent grant; `/sessions/turns` rejects without consent ref |
| Token cost / volume | Cheap/local model (Ollama) for distill + curate; debounce + batch; sample; distill on rollover only |
| Noise vs. signal | Distill prompt extracts only durable knowledge; curator compacts further |
| Contradictions / staleness | Curator supersedes by recency + confidence with provenance |
| Wiki XSS (untrusted agent markdown) | Sanitize rendered HTML (allowlist) — unlike the trusted README page |
| Reprocessing | Keep `source_ref`/`sources` so pages recompute from raw |

## 12. Open questions
- Email delivery for member invites / sign-in OTP codes (no mailer wired yet;
  OTP is shown on-page in dev mode and logged in prod).
- Curator cadence + thresholds (debounce N, scheduled pass interval).
- Whether to keep the public `/memory` page or redirect it to `/app`.
- Per-scope retention for the raw transcript archive.
