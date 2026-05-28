---
description: 
alwaysApply: true
---

# Working on teamshared

Conventions for anything that edits this repo (you, future me, an agent).

## Architecture in one paragraph

`teamshared` is an MCP server. Each MCP tool in [`src/teamshared/server/tools.py`](src/teamshared/server/tools.py)
is a thin façade over one of the four pillars in [`src/teamshared/memory/`](src/teamshared/memory).
The server fetches its shared resources (Redis client, Mem0 instance, Postgres
pool) through [`teamshared.server.state.get_state()`](src/teamshared/server/state.py).
The distillation worker is a separate process that reads a Redis queue,
calls an LLM via [`teamshared.distill.summarizer`](src/teamshared/distill/summarizer.py),
and writes back through the same Mem0 instance.

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
- Teammate onboarding should cover the `teamshared` Cursor plugin (MCP + rule + continual learning), not just a standalone `~/.cursor/mcp.json` snippet.
- Get-token/onboarding pages should ship the full `teamshared.mdc` rule markdown with install instructions, not only the MCP JSON block.

## Learned Workspace Facts

- The Python package, CLI, and env prefix are `teamshared` / `TEAMSHARED_*`.
- Team production MCP host is `https://actx.teamshared.com` (`/health`, `/mcp`, `/get-token/...`); `mcp.teamshared.com` is retired.
- Continual-learning workspace slug: repo root path with leading `/` removed and `/` replaced by `-` (this repo: `Users-chad-code-sapien-actx`).
- On Spark, run the CLI through Docker Compose or Makefile targets; prefer `make invite-create-host` (exec into the running server) over `make invite-create` so invites land in `/data/invites.json`. There is no global `teamshared` on shell PATH.
- Self-service invites and token onboarding use agent types (`cursor`, `codex`, `hermes`, `claude`, `openclaw`), not personalized names; `cursor-chad` normalizes to `cursor`.
- Teammate curl onboarding: `curl -fsS 'https://actx.teamshared.com/?invite=CODE&agent=TYPE'` returns the raw bearer token as plain text.
- Spark deployments with host Ollama use `make build-ollama-host`; set `TEAMSHARED_PG_PORT` / `TEAMSHARED_REDIS_PORT` in `.env` when host 5432/6379 are already taken.
- One-off compose CLI targets (`migrate`, `seed`, `token-mint`, `invite-create`) use `--no-deps` so they do not start conflicting Postgres/Redis containers.
- `teamshared` Cursor plugin lives at `plugins/teamshared/`; local install is `ln -sf <repo>/plugins/teamshared ~/.cursor/plugins/local/teamshared` then reload Cursor (requires Bun for hooks).
- Plugin MCP wiring reads `TEAMSHARED_URL` and `TEAMSHARED_TOKEN` from the environment (see plugin `mcp.json`); Cursor must inherit those vars at launch.
- Cursor does not auto-fetch remote `.mdc` rules from MCP on connect; distribute agent guidance via the plugin bundle or bundled rule on get-token pages.
