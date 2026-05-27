# Working on sptx

Conventions for anything that edits this repo (you, future me, an agent).

## Architecture in one paragraph

`sptx` is an MCP server. Each MCP tool in [`src/sptx/server/tools.py`](src/sptx/server/tools.py)
is a thin façade over one of the four pillars in [`src/sptx/memory/`](src/sptx/memory).
The server fetches its shared resources (Redis client, Mem0 instance, Postgres
pool) through [`sptx.server.state.get_state()`](src/sptx/server/state.py).
The distillation worker is a separate process that reads a Redis queue,
calls an LLM via [`sptx.distill.summarizer`](src/sptx/distill/summarizer.py),
and writes back through the same Mem0 instance.

## Hard rules

- **No business logic in tool functions.** Tool bodies do (1) resolve agent
  identity, (2) call into `sptx.memory.*`, (3) return a JSON-serializable dict.
- **Mem0 is sync.** Always `await loop.run_in_executor(...)` around its calls.
- **Add tests before extending the tool surface.** A new tool without a test
  in `tests/` is a regression risk.
- **Imports at the top of the file.** No inline imports inside functions
  except inside `sptx/cli.py` (where heavy server deps are lazy-loaded so
  `sptx token mint` stays fast) and inside FastMCP lifespan handlers where
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
 [`sptx/memory/semantic.py`](src/sptx/memory/semantic.py) we work around it
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

1. Define the schema in [`sptx/memory/types.py`](src/sptx/memory/types.py).
2. Add the pillar method (e.g. `WorkingMemory.foo(...)`) with a focused test.
3. Add the tool in [`sptx/server/tools.py`](src/sptx/server/tools.py) using
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

Integration tests require `SPTX_PG_*` and `SPTX_REDIS_URL` to point at the
compose stack (defaults match).

On this machine, sptx publishes Postgres on **host port 5433** (`SPTX_PG_PORT=5433`
in `.env`) because `poq-monorepo-postgres-1` already binds 5432. The
container-internal port stays 5432, so service-to-service traffic over the
compose network is unaffected — only host-side tools (`pytest -m integration`,
`psql`) need the 5433 override.

Always invoke compose via `make`, or pass `--env-file .env` explicitly.
`docker compose -f infra/docker-compose.yml ...` without `--env-file` silently
ignores the repo-root `.env` and falls back to the hardcoded defaults
(including `SPTX_PG_PORT=5432`, which then collides with `poq`). The Makefile
wraps this via `COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml`.

## Migrations

SQL files in [`infra/migrations/`](infra/migrations) are applied in lexical
order by `sptx migrate` and recorded in `sptx_migrations`. Never rewrite an
applied migration; add a new one.

## Releasing

Bump `version` in [`pyproject.toml`](pyproject.toml) and `src/sptx/__init__.py`,
then `git tag v<x.y.z>`. CI (when added in phase 7) will build and push the
image.

[`infra/Dockerfile`](infra/Dockerfile) must `COPY README.md` alongside
`pyproject.toml`. Hatchling validates `readme = "README.md"` during the wheel
build, so dropping it breaks both the `server` and `distiller` images.
