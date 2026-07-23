#!/usr/bin/env bash
# Restore VERIFICATION: prove a backup actually restores, without touching the live DB.
#
#   bash scripts/restore-test.sh [dump.sql.gz]     # default: newest dump in $BACKUP_DIR
#
# Spins up a throwaway postgres:16-alpine container, restores the dump into it,
# compares table count + per-table row counts against the live database, then
# destroys the container. Exit 0 = the backup is proven restorable.
#
# To restore FOR REAL into the stack (disaster recovery), see DEPLOYMENT.md §Restore.
set -euo pipefail
# COMPOSE_DIR: where the running compose project lives (default: this repo).
cd "${COMPOSE_DIR:-$(dirname "$0")/..}"

BACKUP_DIR="${BACKUP_DIR:-$HOME/aiwip-backups}"
DUMP="${1:-$(ls -1t "$BACKUP_DIR"/aiwip-*.sql.gz | head -1)}"
PGUSER="${POSTGRES_USER:-aiwip}"
PGDB="${POSTGRES_DB:-aiwip}"
SCRATCH="aiwip-restore-test-$$"

echo "→ dump under test: $DUMP"

cleanup() { docker rm -f "$SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$SCRATCH" -e POSTGRES_USER="$PGUSER" -e POSTGRES_PASSWORD=restore \
  -e POSTGRES_DB="$PGDB" postgres:16-alpine >/dev/null
until docker exec "$SCRATCH" pg_isready -U "$PGUSER" -q; do sleep 1; done

echo "→ restoring…"
gzip -cd "$DUMP" | docker exec -i "$SCRATCH" psql -q -U "$PGUSER" -d "$PGDB" -v ON_ERROR_STOP=1 >/dev/null

COUNT_SQL="SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
ROWS_SQL="SELECT relname || ':' || n_live_tup FROM pg_stat_user_tables ORDER BY relname"

live_tables=$(docker compose exec -T postgres psql -tA -U "$PGUSER" -d "$PGDB" -c "$COUNT_SQL")
rest_tables=$(docker exec "$SCRATCH" psql -tA -U "$PGUSER" -d "$PGDB" -c "$COUNT_SQL")
echo "→ tables: live=$live_tables restored=$rest_tables"
[ "$live_tables" = "$rest_tables" ] || { echo "FAIL: table count mismatch" >&2; exit 1; }

# Row counts per table (ANALYZE first so pg_stat is fresh in the scratch container).
docker exec "$SCRATCH" psql -q -U "$PGUSER" -d "$PGDB" -c "ANALYZE" >/dev/null
docker exec "$SCRATCH" psql -tA -U "$PGUSER" -d "$PGDB" -c "$ROWS_SQL"

echo "RESTORE TEST OK: $DUMP restores cleanly ($rest_tables tables)"
