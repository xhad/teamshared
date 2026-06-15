# Deploying teamshared on Railway

Compose stack → six Railway services in one project (pgvector, Redis,
server, distiller, curator, agent-worker). No Tailscale, no self-hosted TLS,
no Caddy.
Bearer-token auth in [`teamshared.auth`](../src/teamshared/auth.py) is what
protects the public endpoint, so don't disable it.

```
┌──────────┐ ┌────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│ pgvector │ │ Redis  │ │ teamshared-│ │ teamshared-│ │ teamshared-│
│ (image)  │ │(templ.)│ │ server     │ │ distiller  │ │ curator    │
│ + volume │ │        │ │  public ✓  │ │ (worker)   │ │ (curator)  │
│          │ │        │ │  /data vol │ │            │ │            │
│          │ │        │ │  predeploy │ │            │ │            │
│          │ │        │ │  migrate   │ │            │ │            │
└────┬─────┘ └───┬────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
     │           │            │              │              │
     └───────────┴────────────┴──────────────┴──────────────┘
              private networking (*.railway.internal)
```

Neo4j (the graph pillar) is optional; when it is omitted `memory_graph_*`
degrades to a no-op and `/health` reports `graph: disabled` (which does not
degrade overall status). To enable it, add a Neo4j service (image `neo4j:5`,
a volume at `/data`, `NEO4J_AUTH=neo4j/<password>` and
`NEO4J_server_default__listen__address=::` so it binds Railway's IPv6 private
network) and set `TEAMSHARED_NEO4J_URL=bolt://neo4j.railway.internal:7687`
plus `TEAMSHARED_NEO4J_USER` / `TEAMSHARED_NEO4J_PASSWORD` on the server,
distiller, and agent-worker.

> The four app services share one Dockerfile and differ only by start
> command. Each ships a config file: [`railway.server.toml`](railway.server.toml),
> [`railway.distiller.toml`](railway.distiller.toml),
> [`railway.curator.toml`](railway.curator.toml), and
> [`railway.agent-worker.toml`](railway.agent-worker.toml).

## CLI-driven deploy (alternative to the dashboard)

The whole stack can be stood up with the `railway` CLI. Because the CLI cannot
set a service's *custom config file path*, deploy each app service with
`railway up` from the repo root using a temporary root `railway.toml` (copy the
matching `infra/railway.*.toml` contents into `./railway.toml`, run
`railway up --service <svc> --detach`, then repeat for the next service). The
pgvector image does **not** auto-emit `DATABASE_URL`, so construct the DSN from
the Postgres service's private domain (see the variables table below). Pin the
server's port with `PORT=8077` and `railway domain --port 8077` so Railway's
proxy targets the same port the Dockerfile's `TEAMSHARED_PORT=8077` binds.

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
3. **Settings → Volumes**: attach a 1 GB volume mounted at `/data` for
   `invites.json` and other small on-disk state.
4. **Settings → Networking**: generate a public domain. Note it down; this
   is what your agents will point at.
5. **Variables**: set the following. Use Railway's `${{Service.VAR}}`
   reference syntax so these auto-update on rotation.

   | Var | Value |
   |---|---|
   | `TEAMSHARED_DEPLOYMENT_ENV` | `production` *(runs the startup safety checks in [`config_validate.py`](../src/teamshared/config_validate.py))* |
   | `TEAMSHARED_PG_DSN` | `postgresql://teamshared:${{postgres.POSTGRES_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/teamshared` |
   | `TEAMSHARED_REDIS_URL` | `${{Redis.REDIS_URL}}` |
   | `TEAMSHARED_PG_APP_USER` | `teamshared_app` *(RLS role; see step 5b)* |
   | `TEAMSHARED_PG_APP_PASSWORD` | *(long random string)* |
   | `TEAMSHARED_SESSION_SECRET` | *(long random string; console sign-in)* |
   | `TEAMSHARED_JOB_SIGNING_SECRET` | *(long random string; MUST match distiller + curator)* |
   | `TEAMSHARED_CONNECTOR_ENCRYPTION_KEY` | *(base64/hex 32-byte key)* |
   | `TEAMSHARED_MINT_SECRET` | *(long random string; enables `POST /tokens/mint` for teammates)* |
   | `TEAMSHARED_INVITES_FILE` | `/data/invites.json` |
   | `TEAMSHARED_PUBLIC_URL` | *(your public domain, e.g. `https://teamshared-server-production.up.railway.app`)* |
   | `PORT` / `TEAMSHARED_PORT` | `8077` *(pin both; the Dockerfile binds 8077)* |
   | `OPENAI_API_KEY` | *(your key)* |
   | `TEAMSHARED_EMBED_MODEL` | `text-embedding-3-small` *(default)* |
   | `TEAMSHARED_LLM_MODEL` | `gpt-4o-mini` *(default)* |

   The pgvector *image* (unlike Railway's managed Postgres template) does not
   emit `DATABASE_URL`, so the DSN above is built from the Postgres service's
   private domain. For console OTP delivery in production also set the
   `TEAMSHARED_SMTP_*` vars (without them the sign-in code can't be emailed).

6. Deploy. The pre-deploy hook applies migrations idempotently; the main
   process is `teamshared serve --transport http`.

### 2b. Bootstrap the RLS app role

`TEAMSHARED_PG_APP_USER` makes the app connect as a `NOSUPERUSER NOBYPASSRLS`
role so Row-Level Security is actually enforced. That role must be created
once, **after** migrations, by an admin connection. Railway's `preDeployCommand`
is a single, non-shell command, so it can't chain `migrate && provision-app-role`
— run the provisioning out-of-band the first time (the role then persists in the
Postgres volume):

```bash
# register an SSH key with Railway once, then write an OpenSSH config block
railway ssh keys add --key ~/.ssh/id_rsa.pub
railway ssh config --service teamshared-server -i ~/.ssh/id_rsa

# create the role and verify tenant isolation inside the running container
ssh -o StrictHostKeyChecking=accept-new railway-teamshared-server \
  "teamshared provision-app-role && teamshared verify-rls"
```

`verify-rls` should print `RLS verification passed.` (every table returns zero
rows without an org context). If `railway ssh` is unavailable, run the same SQL
as the Postgres superuser via `psql` against the `postgres` service.

## 3. Deploy `teamshared-distiller`, `teamshared-curator`, and `teamshared-agent-worker`

These are worker services from the same GitHub repo with no public port and no
healthcheck — only their start command differs.

1. New service → same GitHub repo. **Settings → Source**: custom config file
   path `/infra/railway.distiller.toml` (start command `teamshared worker`).
2. Repeat for a second service with `/infra/railway.curator.toml` (start
   command `teamshared curator`).
3. Repeat for a third service with `/infra/railway.agent-worker.toml` (start
   command `teamshared agent-worker`). This one consumes the Redis `agent:runs`
   stream and executes Work Board tasks, so it also needs the LLM-provider key
   (`OPENROUTER_API_KEY` or `OPENAI_API_KEY`) and the `TEAMSHARED_NEO4J_*` vars
   if the graph pillar is enabled. Its heartbeat surfaces as `agent-worker` in
   the server's `/health`.
4. **Variables** on each (workers don't mint tokens or serve HTTP, but they DO
   need the RLS role and a matching job-signing secret):

   | Var | Value |
   |---|---|
   | `TEAMSHARED_DEPLOYMENT_ENV` | `production` |
   | `TEAMSHARED_PG_DSN` | `postgresql://teamshared:${{postgres.POSTGRES_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/teamshared` |
   | `TEAMSHARED_REDIS_URL` | `${{Redis.REDIS_URL}}` |
   | `TEAMSHARED_PG_APP_USER` / `TEAMSHARED_PG_APP_PASSWORD` | same as the server |
   | `TEAMSHARED_JOB_SIGNING_SECRET` | same value as the server |
   | `TEAMSHARED_CONNECTOR_ENCRYPTION_KEY` | same value as the server |
   | `OPENAI_API_KEY` | *(your key)* |

4. Deploy. The distiller polls the `working:distill:queue` Redis list and
   summarizes closed sessions; the curator consumes the debounced curate queue
   and (re)writes wiki pages. Their heartbeats show up in the server's `/health`.

> Note: over Railway's private network the workers' idle blocking `BLPOP` polls
> can log periodic `distill_pop_failed`/`curate_pop_failed` "Timeout reading
> from redis" warnings. These are cosmetic — real jobs are popped immediately
> when enqueued, and the heartbeat writes still succeed (`/health` stays `ok`).

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

The response includes `"token": "tsk_..."` once — copy it into MCP `Authorization`.

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
  the service settings; API keys live in Postgres. The `/data` volume holds
  invites and other small files. Point `scripts/backup.sh` at the public
  domain via `railway run` on a GitHub Actions cron if needed.
- **Scaling the server**: horizontal replicas are safe — the server is
  stateless, all state lives in Postgres/Redis. Just don't run multiple
  distiller replicas; the queue is `BLPOP`-based and one consumer is the
  intended topology.
- **Rotating tokens**: mint a new key via console `/app/keys` or
  `teamshared token mint <agent>` over `railway run`, update MCP configs, then
  revoke the old API key in the console.
- **Costs**: a single-replica server + distiller + curator + pgvector + Redis
  on Railway's Hobby plan runs around $5–20/mo depending on Mem0 churn.
  Embedding API calls dominate once you have a few teammates writing
  daily.
