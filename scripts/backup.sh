#!/usr/bin/env bash
# actx nightly backup.
#
# Dumps Postgres (covers Mem0's tables + ours) and the Redis AOF, into a
# timestamped tarball under $ACTX_BACKUP_DIR (default ./backups). Keeps the
# last $ACTX_BACKUP_KEEP archives (default 14).
#
# Suggested cron entry (host with the compose stack):
#
#   15 3 * * *  /path/to/actx/scripts/backup.sh >> /var/log/actx-backup.log 2>&1
#
# Env:
#   ACTX_PG_*         -- standard actx Postgres connection settings.
#   ACTX_REDIS_HOST   -- defaults to localhost (or `redis` inside compose).
#   ACTX_BACKUP_DIR   -- target directory (default ./backups).
#   ACTX_BACKUP_KEEP  -- max archives to keep (default 14).

set -euo pipefail

PG_HOST="${ACTX_PG_HOST:-localhost}"
PG_PORT="${ACTX_PG_PORT:-5432}"
PG_USER="${ACTX_PG_USER:-actx}"
PG_DB="${ACTX_PG_DB:-actx}"
REDIS_HOST="${ACTX_REDIS_HOST:-localhost}"
REDIS_PORT="${ACTX_REDIS_PORT:-6379}"
BACKUP_DIR="${ACTX_BACKUP_DIR:-./backups}"
KEEP="${ACTX_BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[$(date -Iseconds)] actx backup $STAMP starting"

# Postgres logical dump (Mem0 + procedures + audit).
PGPASSWORD="${ACTX_PG_PASSWORD:-actx}" pg_dump \
  -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
  --format=custom --compress=6 \
  "$PG_DB" > "$WORK/actx-pg.dump"

# Redis: trigger a SAVE then copy the rdb. The AOF is also fine but the rdb
# is single-file.
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SAVE > /dev/null
# Compose mounts redis data at /data; outside compose, this path is whatever
# `redis-cli config get dir` reports. Try CLI first, fall back to default.
REDIS_DIR="$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" CONFIG GET dir | tail -1)"
if [[ -f "$REDIS_DIR/dump.rdb" ]]; then
  cp "$REDIS_DIR/dump.rdb" "$WORK/actx-redis.rdb"
else
  echo "  warn: $REDIS_DIR/dump.rdb not readable (rdb skipped)"
fi

# Tokens file (small, but worth saving so we don't have to remint everyone).
if [[ -f .actx/tokens.json ]]; then
  cp .actx/tokens.json "$WORK/tokens.json"
fi

OUT="$BACKUP_DIR/actx-$STAMP.tar.gz"
tar -czf "$OUT" -C "$WORK" .
echo "[$(date -Iseconds)] wrote $OUT"

# Prune old archives.
ls -1t "$BACKUP_DIR"/actx-*.tar.gz 2>/dev/null | tail -n "+$((KEEP+1))" | xargs -r rm -f

echo "[$(date -Iseconds)] actx backup $STAMP done"
