#!/usr/bin/env bash
# teamshared nightly backup.
#
# Dumps Postgres (covers Mem0's tables + ours) and the Redis AOF, into a
# timestamped tarball under $TEAMSHARED_BACKUP_DIR (default ./backups). Keeps the
# last $TEAMSHARED_BACKUP_KEEP archives (default 14).
#
# Suggested cron entry (host with the compose stack):
#
#   15 3 * * *  /path/to/teamshared/scripts/backup.sh >> /var/log/teamshared-backup.log 2>&1
#
# Env:
#   TEAMSHARED_PG_*         -- standard teamshared Postgres connection settings.
#   TEAMSHARED_REDIS_HOST   -- defaults to localhost (or `redis` inside compose).
#   TEAMSHARED_BACKUP_DIR   -- target directory (default ./backups).
#   TEAMSHARED_BACKUP_KEEP  -- max archives to keep (default 14).

set -euo pipefail

PG_HOST="${TEAMSHARED_PG_HOST:-localhost}"
PG_PORT="${TEAMSHARED_PG_PORT:-5432}"
PG_USER="${TEAMSHARED_PG_USER:-teamshared}"
PG_DB="${TEAMSHARED_PG_DB:-teamshared}"
REDIS_HOST="${TEAMSHARED_REDIS_HOST:-localhost}"
REDIS_PORT="${TEAMSHARED_REDIS_PORT:-6379}"
BACKUP_DIR="${TEAMSHARED_BACKUP_DIR:-./backups}"
KEEP="${TEAMSHARED_BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[$(date -Iseconds)] teamshared backup $STAMP starting"

# Postgres logical dump (Mem0 + procedures + audit).
PGPASSWORD="${TEAMSHARED_PG_PASSWORD:-teamshared}" pg_dump \
  -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
  --format=custom --compress=6 \
  "$PG_DB" > "$WORK/teamshared-pg.dump"

# Redis: trigger a SAVE then copy the rdb. The AOF is also fine but the rdb
# is single-file.
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SAVE > /dev/null
# Compose mounts redis data at /data; outside compose, this path is whatever
# `redis-cli config get dir` reports. Try CLI first, fall back to default.
REDIS_DIR="$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" CONFIG GET dir | tail -1)"
if [[ -f "$REDIS_DIR/dump.rdb" ]]; then
  cp "$REDIS_DIR/dump.rdb" "$WORK/teamshared-redis.rdb"
else
  echo "  warn: $REDIS_DIR/dump.rdb not readable (rdb skipped)"
fi

# Tokens file (small, but worth saving so we don't have to remint everyone).
if [[ -f .teamshared/tokens.json ]]; then
  cp .teamshared/tokens.json "$WORK/tokens.json"
fi

OUT="$BACKUP_DIR/teamshared-$STAMP.tar.gz"
tar -czf "$OUT" -C "$WORK" .
echo "[$(date -Iseconds)] wrote $OUT"

# Prune old archives.
ls -1t "$BACKUP_DIR"/teamshared-*.tar.gz 2>/dev/null | tail -n "+$((KEEP+1))" | xargs -r rm -f

echo "[$(date -Iseconds)] teamshared backup $STAMP done"
