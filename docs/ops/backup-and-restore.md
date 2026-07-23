# Backup & Restore

A backup that has never been restored is a hope, not a backup. This page documents the
procedure **and** the verified restore run.

## Backup

`scripts/backup-db.sh` — `pg_dump | gzip` via the running compose Postgres, empty-dump
guard, rotation (newest `KEEP=14` kept).

Cron on the VPS (03:00 daily):

```cron
0 3 * * * cd /path/to/telegram-task-bot && bash scripts/backup-db.sh >> "$HOME/aiwip-backups/backup.log" 2>&1
```

Off-box copy (recommended): rsync `~/aiwip-backups/` to a second location — a failed disk
must not take the dumps with it.

## Restore verification (run it monthly)

`scripts/restore-test.sh [dump]` — spins up a throwaway `postgres:16-alpine`, restores the
newest dump into it, compares table count and prints per-table row counts, destroys the
container. Never touches the live database. Exit 0 = the dump is proven restorable.

## Verified run — 2026-07-23

Executed against the live dev stack (`aiwip` compose project):

```text
$ bash scripts/backup-db.sh
backup ok: …/aiwip-backups/aiwip-20260723-013458.sql.gz ( 24K)

$ bash scripts/restore-test.sh
→ dump under test: …/aiwip-backups/aiwip-20260723-013458.sql.gz
→ restoring…
→ tables: live=20 restored=20
ai_runs:17  alembic_version:1  assignees:3  audit_logs:172  candidate_assignees:9
candidate_labels:0  candidate_messages:17  candidates:17  chats:5  connector_accounts:0
evaluation_cases:0  labels:4  message_attachments:20  messages:74  sync_runs:32
sync_states:5  users:1  work_item_assignees:3  work_item_labels:0  work_items:5
RESTORE TEST OK: aiwip-20260723-013458.sql.gz restores cleanly (20 tables)
```

## Disaster recovery (restore into the real stack)

```bash
docker compose stop api worker bot            # stop writers
gzip -cd "$HOME/aiwip-backups/aiwip-<STAMP>.sql.gz" \
  | docker compose exec -T postgres psql -U aiwip -d aiwip -v ON_ERROR_STOP=1
docker compose start api worker bot
curl -fsS localhost:8000/health/ready         # verify before walking away
```
