---
description: 
alwaysApply: true
---

# Working on teamshared

Conventions for anything that edits this repo (you, future me, an agent).

## Architecture in one paragraph

`teamshared` is an MCP server. Each MCP tool in [`src/teamshared/server/tools.py`](src/teamshared/server/tools.py)
is a thin façade over one of the five pillars in [`src/teamshared/memory/`](src/teamshared/memory).
The server fetches its shared resources (Redis client, Mem0 instance, Postgres
pool) through [`teamshared.server.state.get_state()`](src/teamshared/server/state.py).
The distillation worker is a separate process that reads a Redis queue,
calls an LLM via [`teamshared.distill.summarizer`](src/teamshared/distill/summarizer.py),
and writes back through the same Mem0 instance. A second worker, the **curator**
([`teamshared.distill.curator_worker`](src/teamshared/distill/curator_worker.py)),
consumes a separate debounced Redis queue and (re)synthesizes human-readable
`wiki_pages` articles. Humans interact through the server-rendered **console**
([`teamshared.server.console`](src/teamshared/server/console.py), Jinja2 templates
under `src/teamshared/server/templates/`) mounted at `/app`; it authenticates with
one-time-passcode (OTP) sessions, not bearer tokens, and reads/writes through the
same `ProductionServices` the `/v1` REST API uses.

## Hard rules

- **No business logic in tool functions.** Tool bodies do (1) resolve agent
  identity, (2) call into `teamshared.memory.*`, (3) return a JSON-serializable dict.
- **Mem0 is sync.** Always `await loop.run_in_executor(...)` around its calls.
- **Add tests before extending the tool surface.** A new tool without a test
  in `tests/` is a regression risk.
- **Imports at the top of the file.** No inline imports inside functions
  except inside `teamshared/cli.py` (where heavy server deps are lazy-loaded so
  `teamshared token mint` stays fast) and inside FastMCP lifespan handlers where
  circular imports otherwise occur.
- **Exhaustive `match` on `MemoryKind` and `MemoryScope`.** When you add a new
  variant, update every match/switch and rerun mypy.
- **Mem0 2.0 kwarg contract.** `Memory.search()` and `Memory.get_all()` reject
  top-level `user_id` and `limit`; pass `filters={"user_id": agent}` and
  `top_k=...` instead. `Memory.add()` still takes top-level `user_id`. The
  contract is pinned by [`tests/test_semantic_mem0_calls.py`](tests/test_semantic_mem0_calls.py).
- **Mem0 returns cosine distance in `score`.** The pgvector backend stores
 *distance* (smaller = better) but `score_and_rank` treats it as similarity
 and silently drops the closest matches below `threshold=0.1`. In
 [`teamshared/memory/semantic.py`](src/teamshared/memory/semantic.py) we work around it
 by passing `threshold=0`, over-fetching with a high `top_k`, and converting
 via `1 - distance` at the boundary. Don't remove that flip without also
 re-checking `score_and_rank` upstream.
- **Read paths are agent-unscoped by default.** `memory_recall` and
 `memory_episodes_list` must default to no agent filter on the durable
 pillars. The shared-brain promise lives in `Recall.search`, where `agent=`
 is an opt-in filter for callers who explicitly want one agent's slice and
 `caller=` (a separate parameter) drives only the working-memory lookup.
 Never collapse the two back into one parameter — that's exactly the
 regression that broke cross-agent visibility before. Tests in
 [`tests/test_recall_ranking.py`](tests/test_recall_ranking.py) and
 [`tests/test_server_tools.py`](tests/test_server_tools.py) pin this; the
 cross-agent smoke ([`scripts/smoke_cross_agent.py`](scripts/smoke_cross_agent.py))
 is the executable spec. Write paths (`memory_remember`,
 `memory_session_open`, `memory_procedure_set`, `memory_graph_relate`) keep
 using `_resolve_agent` because writes need a stable author for attribution.

## Adding a memory tool

1. Define the schema in [`teamshared/memory/types.py`](src/teamshared/memory/types.py).
2. Add the pillar method (e.g. `WorkingMemory.foo(...)`) with a focused test.
3. Add the tool in [`teamshared/server/tools.py`](src/teamshared/server/tools.py) using
   typed `Annotated[..., Field(description=...)]` parameters so MCP clients
   get clean descriptors.
4. Update `README.md`'s tool table.

## Running tests

```bash
pip install -e '.[dev]'
pytest                                  # unit tests (mocked stores)
docker compose -f infra/docker-compose.yml up -d postgres redis
pytest -m integration                   # hits real Postgres + Redis
```

Integration tests require `TEAMSHARED_PG_*` and `TEAMSHARED_REDIS_URL` to point at the
compose stack (defaults match).

On this machine, teamshared publishes Postgres on **host port 5433** (`TEAMSHARED_PG_PORT=5433`
in `.env`) because `poq-monorepo-postgres-1` already binds 5432. The
container-internal port stays 5432, so service-to-service traffic over the
compose network is unaffected — only host-side tools (`pytest -m integration`,
`psql`) need the 5433 override.

Always invoke compose via `make`, or pass `--env-file .env` explicitly.
`docker compose -f infra/docker-compose.yml ...` without `--env-file` silently
ignores the repo-root `.env` and falls back to the hardcoded defaults
(including `TEAMSHARED_PG_PORT=5432`, which then collides with `poq`). The Makefile
wraps this via `COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml`.

## Migrations

SQL files in [`infra/migrations/`](infra/migrations) are applied in lexical
order by `teamshared migrate` and recorded in `teamshared_migrations`. Never rewrite an
applied migration; add a new one.

## Releasing

Bump `version` in [`pyproject.toml`](pyproject.toml) and `src/teamshared/__init__.py`,
then `git tag v<x.y.z>`. CI (when added in phase 7) will build and push the
image.

[`infra/Dockerfile`](infra/Dockerfile) must `COPY README.md` alongside
`pyproject.toml`. Hatchling validates `readme = "README.md"` during the wheel
build, so dropping it breaks both the `server` and `distiller` images.

## Learned User Preferences

- Keep Cursor hook and continual-learning state under `~/.cursor`, not committed in the repo.
- Prefer storing the continual-learning transcript index on the teamshared server via `memory_state_get` / `memory_state_set` (token+repo scoped) when MCP is available; fall back to `~/.cursor/hooks/state/continual-learning/<workspace-slug>/`.
- Teammate onboarding should use the unified curl installer (`install.sh` on teamshared.com) or the `teamshared` Cursor plugin (MCP + rule + continual learning), not a standalone `~/.cursor/mcp.json` snippet alone.
- Remote install uses one `install.sh` with interactive prompts (a harness multiple-choice selector plus a bearer-token paste written into MCP config), not environment variables (`TEAMSHARED_HARNESS` / `TEAMSHARED_TOKEN` / `TEAMSHARED_INVITE`); no per-harness `.sh` scripts and no invite-redeem flow in the installer.
- Get-token/onboarding pages should ship the full `teamshared.mdc` rule markdown with install instructions (copy-paste from the page), not repo symlinks or MCP JSON alone.

## Learned Workspace Facts

- The Python package, CLI, and env prefix are `teamshared` / `TEAMSHARED_*`.
- Team production host is `https://teamshared.com` (`/health`, `/mcp`, `/get-token`, unified install at `/install.sh` and `/install`); `mcp.teamshared.com` is retired.
- Continual-learning workspace slug: repo root path with leading `/` removed and `/` replaced by `-` (this checkout: `home-chad-code-teamshared` for `/home/chad/code/teamshared`).
- Code-scoped durable memory uses two optional MCP params: `repo=` (workspace path slug, aligns with hooks/`memory_state`) and `github=` (`owner/repo`, stored as `github:<owner>/<repo>` tag, portable across machines). Both softly boost recall; see `plugins/teamshared/rules/teamshared.mdc`.
- There is ONE compose file (`infra/docker-compose.yml`) and ONE Makefile command set — the `docker-compose.ollama-host.yml` override and `build-ollama-host` / `invite-create-host` targets are gone. `server`/`distiller` always run on the compose bridge network and reach a host Ollama via `host.docker.internal` (`extra_hosts: host-gateway`). On Linux/Spark, make the host Ollama reachable from the bridge instead of switching to host networking: run Ollama with `OLLAMA_HOST=0.0.0.0:11434` and allow the docker bridge subnet to 11434 (e.g. `sudo ufw allow from 172.16.0.0/12 to any port 11434 proto tcp`).
- On Spark there is no global `teamshared` on PATH — run the CLI via Docker Compose / Makefile targets (one-off targets `migrate`/`seed`/`token-mint`/`invite-create` pass `--no-deps` so they don't start conflicting Postgres/Redis; they share the `teamshareddata` volume so invites land in `/data/invites.json`); override `TEAMSHARED_PG_PORT` / `TEAMSHARED_REDIS_PORT` in `.env` when host 5432/6379 are taken. The server runs on the Spark box and is exposed publicly at `teamshared.com` through a proxy/tunnel (railtail / Cloudflare Tunnel), so users don't need Tailscale.
- Self-service token onboarding uses agent types (`cursor`, `codex`, `hermes`, `claude`, `openclaw`), not personalized names (`cursor-chad` → `cursor`); redeem via `curl -fsS 'https://teamshared.com/?invite=CODE&agent=TYPE'` for the raw bearer token.
- `teamshared` Cursor plugin at `plugins/teamshared/` bundles MCP wiring, recall rule, continual-learning hooks, and client snippets; install via `curl -fsSL https://teamshared.com/install.sh` (remote assets under `/install/assets/`), marketplace (`/add-plugin teamshared`), or symlink to `~/.cursor/plugins/local/teamshared`.
- Legacy names `actx`, `sptx`, `actx-memory`, and `sptx-memory` are retired; use `teamshared` for package, plugin, and MCP server naming.
- `teamshared seed` loads starter procedural playbooks only; semantic and episodic memory come from `memory_remember` and session distillation.
- MCP wiring puts the URL and bearer token **inline** in the client config (e.g. `~/.cursor/mcp.json` `headers.Authorization`), written by `install.sh` / the `/get-token` page. Tokens are org-bound `tsk_*` API keys (invite redeem or `teamshared token mint`). No `TEAMSHARED_URL` / `TEAMSHARED_TOKEN` env vars are required client-side; the Cursor plugin no longer ships an env-based `mcp.json` (it was a redundant broken duplicate). Agents must not run shell commands to probe `TEAMSHARED_*` env vars — use the `health` MCP tool to check connectivity.
- Cursor does not auto-fetch remote `.mdc` rules from MCP on connect; distribute agent guidance via the plugin bundle or bundled rule on get-token pages.
- **Cloud Agents** read committed repo rules: `.cursor/rules/teamshared.mdc` (keep in sync with `plugins/teamshared/rules/teamshared.mdc`). Do not gitignore `.cursor/rules/`; only ignore `.cursor/mcp.json` and local plugin/hook state.
- Conversation capture is server-side: a `ToolCallCaptureMiddleware` plus the `POST /sessions/turns` ingest endpoint ([src/teamshared/server/capture.py](src/teamshared/server/capture.py)) record turn-by-turn natural-language conversation across harnesses (gated by `capture_enabled`), so capture does not depend on Cursor-only `.ts` hooks; supplemental hooks ship for cursor and hermes.
- `GET /memory` is the public (no-auth) memory status dashboard rendered in [`src/teamshared/server/dashboard.py`](src/teamshared/server/dashboard.py) as zero-dependency f-string HTML (CSS bars + inline-SVG donut), wired in `app.py` and whitelisted in `auth.py`. Its stats come from `WorkingMemory.stats()` (Redis SCAN), `SemanticEpisodicStore.stats()`/`list_recent()` (direct SQL on the Mem0 `teamshared_memories` payload JSONB), and `ProceduralStore.stats()` — not the MCP tool surface. Sections degrade to "unavailable" instead of 500.
- The human-facing **console** lives at `/app` ([`src/teamshared/server/console.py`](src/teamshared/server/console.py), Jinja2 templates under `src/teamshared/server/templates/`), registered via `register_console_routes` and whitelisted in `auth.py` (prefix `/app`). It uses **one-time-passcode (OTP) sign-in** (email → short numeric code → `ts_session` cookie), not bearer tokens, and there is **no `/admin` endpoint** (removed — its auth moved into the console). OTPs are **email-only**: `WorkingMemory.set_login_otp(email, code, …)` / `verify_login_otp(email, code) -> bool` store a hashed, single-use code in Redis (`TEAMSHARED_OTP_TTL_SECONDS` TTL default 30s, `TEAMSHARED_OTP_MAX_ATTEMPTS` cap) — no `user_id` is bound; which org(s) the email belongs to is resolved *after* verifying. `services.working` is the single shared `WorkingMemory` (owned by `ProductionServices`, also handed to `ServerState`). Code delivery: `auth_disabled` dev mode shows it on the page; otherwise it's emailed via the stdlib-`smtplib` mailer in [`src/teamshared/server/mailer.py`](src/teamshared/server/mailer.py) (`TEAMSHARED_SMTP_*`, `send_login_code` offloaded to a thread executor). With neither, the code can't be retrieved. **Login is open/self-service**: `login_post` issues a code for *any* email (no enumeration gate); `login_verify` enumerates the email's orgs via `services.accounts.list_orgs` and, if there are none, auto-provisions a fresh personal org (owner) via `signup_org`, then issues the session for the active org. The session JWT carries an `email` claim → `Principal.display`. Email-send failures keep the same code screen and log `console_login_otp_email_failed`. Sections: home (`/app`), wiki (`/app/wiki[/timeline|/playbooks|/topic/{slug}]`), memory explorer (`/app/memory`), agents, people (list + **add member by email** → `POST /app/people/add` → `AdminService.add_member`), orgs (`/app/orgs` list/create/switch via the header org switcher in `base.html`), keys, approvals, consent. The shell context (`_shell`/`_org_context`) is async and adds `orgs`/`active_org_id` for the switcher. Read screens render dedicated templates and degrade to a note instead of 500. Write actions are POST→303 redirect (key mint renders the secret once on the page rather than redirecting), RBAC-enforced via `ctx.authorizer.require` / `AdminService` (`org:admin` for agents/keys/roles/members, `memory:approve` for approvals) and audited. New console write features need tests in [`tests/test_console.py`](tests/test_console.py) (its `_build` helper returns `(client, services)`, stubs `services.authorizer().require` as awaitable, and stubs `services.accounts.list_orgs`).
- **Global identity / multi-tenant orgs**: a human is one global **`accounts`** row (unique lowercased email, [`infra/migrations/013_accounts.sql`](infra/migrations/013_accounts.sql)); each per-org `users` row links via `users.account_id`. `accounts` is a **pre-org, cross-org auth table**: it is RLS-locked (`ENABLE`+`FORCE`, *no* policy = deny-all) and must be touched **only** through SECURITY DEFINER functions over `db.admin()` — `provision_account(email, name)` (idempotent upsert) and `auth_account_orgs(email)` (every active org + per-org `user_id` + role, ordered by `organizations.created_at`). Never query `accounts` under `db.org(...)` — it fails closed. `AccountStore` ([`src/teamshared/identity/accounts.py`](src/teamshared/identity/accounts.py)) wraps both and is wired into `ProductionServices`. `signup_org` ([`src/teamshared/identity/provisioning.py`](src/teamshared/identity/provisioning.py)) now **requires an `accounts=` arg** (upserts the account, passes `account_id` into `TenancyRepository.create_user`, which upserts on `(org_id, email)`); update every `signup_org` call site when touching it. `AdminService.add_member(ctx, email, role)` upserts account + per-org user + membership + RBAC role (idempotent). The legacy single-default-org `provision-default-org` CLI still works but is no longer required for login — emails self-provision. Agent/MCP bearer auth uses `PrincipalResolver` (`tsk_*` API keys → bound org).
- The **wiki** is materialized in the `wiki_pages` table ([`infra/migrations/012_wiki.sql`](infra/migrations/012_wiki.sql), `WikiStore` in [`src/teamshared/memory/wiki.py`](src/teamshared/memory/wiki.py), which also owns the canonical `slugify`). The `curator` worker ([`src/teamshared/distill/curator_worker.py`](src/teamshared/distill/curator_worker.py), run via `teamshared curator`, with its own compose service) consumes a debounced Redis queue: the distiller calls `WorkingMemory.mark_subject_dirty` per fact/decision subject, and after `TEAMSHARED_CURATE_THRESHOLD` updates the subject is enqueued and the curator LLM ([`teamshared.distill.curator.curate`](src/teamshared/distill/curator.py)) (re)writes a versioned page. Console topic pages prefer the curated page and fall back to raw records. Untrusted agent markdown is rendered through the allowlist sanitizer in [`src/teamshared/server/markdown_safe.py`](src/teamshared/server/markdown_safe.py) — never render agent HTML without it.
