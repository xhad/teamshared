# Deploying teamshared on Railway

Compose stack →  four Railway services in one project. No Tailscale, no
self-hosted TLS, no Caddy. Bearer-token auth in [`teamshared.auth`](../src/teamshared/auth.py)
is what protects the public endpoint, so don't disable it.

```
┌────────────────┐  ┌──────────┐  ┌──────────────┐  ┌────────────┐
│ pgvector       │  │ Redis    │  │ teamshared-server  │  │ teamshared-      │
│ (template)     │  │ (template│  │ (Dockerfile) │  │ distiller  │
│                │  │  )       │  │  public ✓    │  │ (Dockerfile│
│  DATABASE_URL  │  │ REDIS_URL│  │  /data vol   │  │   command  │
│                │  │          │  │  pre-deploy  │  │   override)│
│                │  │          │  │  teamshared migrate│  │            │
└────────┬───────┘  └─────┬────┘  └──────┬───────┘  └─────┬──────┘
         │                │              │                │
         └────────────────┴──────────────┴────────────────┘
              private networking (*.railway.internal)
```

## 1. Provision the data services

1. **Postgres with pgvector**: deploy the community
   [pgvector template](https://railway.com/deploy/3jJFCA) into your project.
   Railway's *default* Postgres template does NOT have pgvector, and
   [`infra/migrations/001_init.sql`](migrations/001_init.sql) requires it
   (`CREATE EXTENSION vector`). If you'd rather not use a community template,
   add a custom service from `pgvector/pgvector:pg16` with a Volume mounted
   at `/var/lib/postgresql/data` and the standard `POSTGRES_USER` /
   `POSTGRES_PASSWORD` / `POSTGRES_DB` env vars.

2. **Redis**: deploy Railway's official Redis template. No customization needed.

## 2. Deploy `teamshared-server`

1. New service → "Deploy from GitHub repo" → pick this repo.
2. **Settings → Source**: set the *Custom config file path* to
   `/infra/railway.server.toml`. That single file pins the Dockerfile path,
   healthcheck, and pre-deploy `teamshared migrate` so this guide doesn't drift
   from reality.
3. **Settings → Volumes**: attach a 1 GB volume mounted at `/data`. This is
   where `tokens.json` lives — without it your bearer tokens evaporate on
   every redeploy.
4. **Settings → Networking**: generate a public domain. Note it down; this
   is what your agents will point at.
5. **Variables**: set the following. Use Railway's `${{Service.VAR}}`
   reference syntax so these auto-update on rotation.

   | Var | Value |
   |---|---|
   | `TEAMSHARED_PG_DSN` | `${{Postgres.DATABASE_URL}}` |
   | `TEAMSHARED_REDIS_URL` | `${{Redis.REDIS_URL}}` |
   | `TEAMSHARED_TOKENS_FILE` | `/data/tokens.json` |
   | `TEAMSHARED_MINT_SECRET` | *(long random string; enables `POST /tokens/mint` for teammates)* |
   | `OPENAI_API_KEY` | *(your key)* |
   | `TEAMSHARED_EMBED_MODEL` | `text-embedding-3-small` *(default; only override if you want a different embedding model)* |
   | `TEAMSHARED_LLM_MODEL` | `gpt-4o-mini` *(default)* |

   `PORT` is injected by Railway automatically; `Settings.port` reads it as
   a fallback so you don't need `TEAMSHARED_PORT`.

6. Deploy. The pre-deploy hook applies migrations idempotently; the main
   process is `teamshared serve --transport http`.

## 3. Deploy `teamshared-distiller`

1. New service → same GitHub repo.
2. **Settings → Source**: custom config file path
   `/infra/railway.distiller.toml`. (Different toml because the start
   command is `teamshared worker`, no public port, no healthcheck.)
3. **Variables**: same as the server *minus* `TEAMSHARED_TOKENS_FILE` (the
   distiller doesn't read tokens):

   | Var | Value |
   |---|---|
   | `TEAMSHARED_PG_DSN` | `${{Postgres.DATABASE_URL}}` |
   | `TEAMSHARED_REDIS_URL` | `${{Redis.REDIS_URL}}` |
   | `OPENAI_API_KEY` | *(your key)* |

4. Deploy. The distiller polls the `working:distill:queue` Redis list and
   summarizes closed sessions.

## 4. Mint tokens

After the first successful deploy of `teamshared-server`, set a long random
`TEAMSHARED_MINT_SECRET` on the server service so teammates can self-serve tokens
over HTTPS (recommended for public domains):

```bash
# on the server (one-time admin setup)
# TEAMSHARED_MINT_SECRET=<long random string>   # Railway variable

# each teammate
curl -fsS -X POST 'https://<your-railway-domain>/tokens/mint' \
  -H 'Content-Type: application/json' \
  -H 'X-Teamshared-Mint-Secret: <TEAMSHARED_MINT_SECRET>' \
  -d '{"agent":"cursor"}'
```

The response includes `"token": "teamshared_..."` once — copy it into `TEAMSHARED_TOKEN`.

Admin fallback (Railway CLI, no HTTP mint secret needed):

```bash
# install Railway CLI: https://docs.railway.app/develop/cli
railway link                       # pick this project
railway run --service teamshared-server teamshared token mint cursor
railway run --service teamshared-server teamshared token mint hermes
railway run --service teamshared-server teamshared token mint openclaw
```

Each call prints the raw token once. Paste it into the agent's MCP config
(see [`src/teamshared/clients/`](../src/teamshared/clients) for snippets) — replace
`https://memory.tailXXXX.ts.net/mcp` with your Railway public domain
(`https://teamshared-server-production.up.railway.app/mcp`).

Or use the HTTP mint endpoint documented above when `TEAMSHARED_MINT_SECRET` is set.

## 5. Verify

```bash
curl -fsS https://<your-railway-domain>/health | jq
# expected: {"status": "ok", "components": {"redis": "ok", "postgres": "ok", "mem0": "ok"}}
```

If `mem0` reports `not_ready`, the server is still warming Mem0's first
connection — it lazy-initializes the embedding/LLM clients on first call.
A subsequent `memory_remember` settles it.

## Operational notes

- **Backups**: Railway's pgvector template snapshots are configurable in
  the service settings; for tokens, `tokens.json` lives on the attached
  Volume which Railway also snapshots. If you need stronger guarantees,
  point `scripts/backup.sh` at the public domain via `railway run` on a
  GitHub Actions cron.
- **Scaling the server**: horizontal replicas are safe — the server is
  stateless, all state lives in Postgres/Redis. Just don't run multiple
  distiller replicas; the queue is `BLPOP`-based and one consumer is the
  intended topology.
- **Rotating tokens**: same as anywhere — `teamshared token revoke <prefix>`
  then `teamshared token mint <agent>` over `railway run`, push the new token
  to the agent.
- **Costs**: a single-replica server + distiller + pgvector + Redis on
  Railway's Hobby plan runs around $5–15/mo depending on Mem0 churn.
  Embedding API calls dominate once you have a few teammates writing
  daily.
