#!/usr/bin/env bash
# Nightly Postgres backup for the AIWIP stack.
#
# Cron on the VPS (03:00 daily, keep 14 days):
#   0 3 * * * cd /path/to/telegram-task-bot && bash scripts/backup-db.sh >> "$HOME/aiwip-backups/backup.log" 2>&1
#
# Restore procedure + the verified restore test: scripts/restore-test.sh
set -euo pipefail
# COMPOSE_DIR: where the running compose project lives (default: this repo).
cd "${COMPOSE_DIR:-$(dirname "$0")/..}"

BACKUP_DIR="${BACKUP_DIR:-$HOME/aiwip-backups}"
KEEP="${KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/aiwip-$STAMP.sql.gz"

docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-aiwip}" -d "${POSTGRES_DB:-aiwip}" --no-owner \
  | gzip > "$FILE"

# A dump that gunzips to nothing is a failed backup — fail loudly, don't rotate.
if [ "$(gzip -cd "$FILE" | head -c 64 | wc -c)" -eq 0 ]; then
  echo "ERROR: empty dump $FILE" >&2
  exit 1
fi

# Rotation: keep the newest $KEEP dumps.
ls -1t "$BACKUP_DIR"/aiwip-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -- "$old"
done

echo "backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
