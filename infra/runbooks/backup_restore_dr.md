# Backup, Restore & Disaster Recovery Runbook

Scope: the multi-tenant teamshared platform (Postgres + pgvector, Redis,
connector token vault). Targets: **RPO ≤ 15 min**, **RTO ≤ 1 hour** for the
shared tier; dedicated-tier tenants inherit their own SLAs.

## 1. What holds state

| Store | Holds | Loss impact |
|---|---|---|
| Postgres | orgs, identities, RBAC, `memory_items/chunks/embeddings`, procedures, audit, connectors | Critical — source of truth |
| Redis | working sessions, queue streams, quotas, rate-limit counters | Recoverable — ephemeral/derivable |
| Secrets (KMS/env) | `connector_encryption_key`, `pg_app_password`, `session_secret`, `api_admin_secret` | Critical — without the data key, encrypted connector tokens are unrecoverable |

## 2. Backups

### Postgres (primary)
- **Continuous**: WAL archiving to object storage (`archive_mode=on`).
- **Base backup**: nightly `pg_basebackup` (or managed provider snapshot).
- **Logical** (portability / per-table restore): daily
  `pg_dump --format=custom --no-owner` to encrypted object storage, retained 30 days.
- pgvector data is ordinary table data; HNSW indexes are rebuilt on restore
  (`REINDEX` or recreated by migration `004`).

### Redis
- Treat as a cache/queue. Enable AOF (`appendonly yes`, `appendfsync everysec`)
  so in-flight queue jobs survive a restart. No long-term backup required;
  durable memory is in Postgres.

### Secrets
- `connector_encryption_key` is backed up in the KMS/secret manager with its
  own rotation + recovery policy. **Restoring Postgres without this key leaves
  connector tokens undecryptable** — back them up together.

## 3. Restore drills (run quarterly)

1. Provision a clean Postgres, run `teamshared migrate` (creates schema + RLS).
2. Restore the latest base backup, then replay WAL to the target timestamp
   (PITR) — or `pg_restore` the logical dump.
3. `teamshared provision-app-role` and confirm the app connects as the
   non-superuser role.
4. **Verify isolation**: `teamshared verify-rls` must pass (zero rows without an
   org context).
5. Restore Redis AOF (optional); drain the queue DLQ (`<stream>:dlq`).
6. Smoke: signup a throwaway org, ingest + search, confirm cross-tenant leak
   tests (`pytest -m integration tests/test_tenancy.py`) are green.

## 4. Disaster scenarios

- **Region outage**: fail over to the standby Postgres (streaming replica);
  repoint `TEAMSHARED_PG_*`/`DATABASE_URL`; Redis is re-created empty (queues
  resume, working memory is cold).
- **Accidental tenant data deletion**: PITR to just before the event; if scoped
  to one org, logical-restore that org's rows into a staging DB and copy back
  under its org context.
- **Key compromise**: rotate `connector_encryption_key` (decrypt-with-old,
  re-encrypt-with-new via the `key_id` column), revoke connector OAuth grants,
  rotate `api_keys` (they are hashed; force re-mint).
- **Poison queue jobs**: inspect `<stream>:dlq`, fix the handler, re-enqueue or
  discard.

## 5. Ownership
On-call owns execution; platform lead owns quarterly drill sign-off. Record
each drill's RTO/RPO actuals against targets.
