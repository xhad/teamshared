#!/usr/bin/env bash
# sptx nightly backup.
#
# Dumps Postgres (covers Mem0's tables + ours) and the Redis AOF, into a
# timestamped tarball under $SPTX_BACKUP_DIR (default ./backups). Keeps the
# last $SPTX_BACKUP_KEEP archives (default 14).
#
# Suggested cron entry (host with the compose stack):
#
#   15 3 * * *  /path/to/sptx/scripts/backup.sh >> /var/log/sptx-backup.log 2>&1
#
# Env:
#   SPTX_PG_*         -- standard sptx Postgres connection settings.
#   SPTX_REDIS_HOST   -- defaults to localhost (or `redis` inside compose).
#   SPTX_BACKUP_DIR   -- target directory (default ./backups).
#   SPTX_BACKUP_KEEP  -- max archives to keep (default 14).

set -euo pipefail

PG_HOST="${SPTX_PG_HOST:-localhost}"
PG_PORT="${SPTX_PG_PORT:-5432}"
PG_USER="${SPTX_PG_USER:-sptx}"
PG_DB="${SPTX_PG_DB:-sptx}"
REDIS_HOST="${SPTX_REDIS_HOST:-localhost}"
REDIS_PORT="${SPTX_REDIS_PORT:-6379}"
BACKUP_DIR="${SPTX_BACKUP_DIR:-./backups}"
KEEP="${SPTX_BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[$(date -Iseconds)] sptx backup $STAMP starting"

# Postgres logical dump (Mem0 + procedures + audit).
PGPASSWORD="${SPTX_PG_PASSWORD:-sptx}" pg_dump \
  -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
  --format=custom --compress=6 \
  "$PG_DB" > "$WORK/sptx-pg.dump"

# Redis: trigger a SAVE then copy the rdb. The AOF is also fine but the rdb
# is single-file.
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SAVE > /dev/null
# Compose mounts redis data at /data; outside compose, this path is whatever
# `redis-cli config get dir` reports. Try CLI first, fall back to default.
REDIS_DIR="$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" CONFIG GET dir | tail -1)"
if [[ -f "$REDIS_DIR/dump.rdb" ]]; then
  cp "$REDIS_DIR/dump.rdb" "$WORK/sptx-redis.rdb"
else
  echo "  warn: $REDIS_DIR/dump.rdb not readable (rdb skipped)"
fi

# Tokens file (small, but worth saving so we don't have to remint everyone).
if [[ -f .sptx/tokens.json ]]; then
  cp .sptx/tokens.json "$WORK/tokens.json"
fi

OUT="$BACKUP_DIR/sptx-$STAMP.tar.gz"
tar -czf "$OUT" -C "$WORK" .
echo "[$(date -Iseconds)] wrote $OUT"

# Prune old archives.
ls -1t "$BACKUP_DIR"/sptx-*.tar.gz 2>/dev/null | tail -n "+$((KEEP+1))" | xargs -r rm -f

echo "[$(date -Iseconds)] sptx backup $STAMP done"
