# Argus database restore runbook

Argus backups created by `deploy/scripts/argus-backup-db.sh` use this format:

```text
/opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz
```

The file is a gzipped plain SQL dump. Restore it with `psql`, not `pg_restore`.

## Verify a backup

```bash
gzip -t /opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz
zcat /opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz | head -40
```

`gzip -t` must be silent. Any output or non-zero exit means the archive is not safe to restore.

## Restore to a non-production database

Use this first when validating a backup.

```bash
export RESTORE_DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/DBNAME'
zcat /opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz | psql "$RESTORE_DATABASE_URL"
```

Then run application checks against that restored database.

## Production restore checklist

Do not restore over production casually. A restore is destructive from the application point of view and may overwrite newer operational data.

1. Stop services that write to the database.
2. Confirm the target database is the intended restore target.
3. Verify the backup archive with `gzip -t`.
4. Restore the dump with `psql`.
5. Run migrations and health checks.
6. Start services again.

Example:

```bash
sudo systemctl stop argus-web.service argus-telegram-bot.service

export RESTORE_DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/DBNAME'
gzip -t /opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz
zcat /opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz | psql "$RESTORE_DATABASE_URL"

cd /opt/argus
/opt/argus/.venv/bin/python manage.py migrate --noinput
bash deploy/scripts/argus-doctor.sh

sudo systemctl start argus-web.service argus-telegram-bot.service
```

If the restore target is not empty, create a fresh database or explicitly drop/recreate the target first. Do not pipe a backup into an unknown live database.
