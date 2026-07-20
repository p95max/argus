# Production Operations

This document describes the production operation layer for Argus.

Argus is deployed on a VPS as an internal production service. No public production URL is documented in the repository.

The production stack intentionally avoids Docker. It runs directly on the VPS with a Python virtual environment, Gunicorn, and systemd services/timers to keep RAM, CPU, and disk overhead low on a minimal VPS plan.

## Files

Production helper scripts live in:

```text
deploy/scripts/
```

Systemd service and timer templates live in:

```text
deploy/systemd/
```

Sudoers templates live in:

```text
deploy/sudoers/
```

Installed helper scripts live in:

```text
/usr/local/bin/
```

Systemd units are installed into:

```text
/etc/systemd/system/
```

The auto-deploy sudoers policy is installed into:

```text
/etc/sudoers.d/argus-auto-deploy
```

## Install Or Update Ops Files

Run on the VPS:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

The installer:

- installs `deploy/systemd/argus-*.service` and `deploy/systemd/argus-*.timer`;
- installs `deploy/scripts/argus-*` to `/usr/local/bin` with group `argus` and mode `0750`;
- installs `deploy/sudoers/argus-auto-deploy` to `/etc/sudoers.d/argus-auto-deploy` with mode `0440`;
- validates the installed sudoers policy with `visudo -cf`;
- reloads systemd;
- enables and starts the web and Telegram bot services;
- enables and starts all Argus timers.

Check production state:

```bash
/usr/local/bin/argus-doctor.sh
systemctl list-timers --all | grep argus
```

## Sudoers Policy

Auto-deploy runs as the `argus` Linux user. The deploy script must restart the web and Telegram bot services after a successful pull, migration, collectstatic, and Django deploy check.

To avoid storing or prompting for an interactive sudo password, production uses a narrow sudoers rule. Auto-deploy may restart only the runtime services:

```text
/usr/bin/systemctl restart argus-web.service argus-telegram-bot.service
```

Telegram may enqueue only the predefined deploy service:

```text
/usr/bin/systemctl --no-block start argus-auto-deploy.service
```

The Telegram bot may control only the Gmail polling timer/service:

```text
/usr/bin/systemctl enable --now argus-check-gmail.timer
/usr/bin/systemctl disable --now argus-check-gmail.timer
/usr/bin/systemctl --no-block start argus-check-gmail.service
```

The repository template is:

```text
deploy/sudoers/argus-auto-deploy
```

Installed target:

```text
/etc/sudoers.d/argus-auto-deploy
```

Manual validation:

```bash
sudo visudo -cf /etc/sudoers.d/argus-auto-deploy
sudo -n systemctl restart argus-web.service argus-telegram-bot.service
sudo -n systemctl --no-block start argus-check-gmail.service
```

Expected result for the restart check:

```text
0
```

## Services

Argus production is managed by these main services:

```text
argus-web.service              Django/Gunicorn web app
argus-telegram-bot.service     Telegram polling bot
```

Check service status:

```bash
systemctl status argus-web.service --no-pager -l
systemctl status argus-telegram-bot.service --no-pager -l
```

View logs:

```bash
sudo journalctl -u argus-web.service -n 100 --no-pager -l
sudo journalctl -u argus-telegram-bot.service -n 100 --no-pager -l
```

## Timers

Background jobs are managed by these timers:

```text
argus-check-gmail.timer        Fetch Gmail and create alerts
argus-unread-reminders.timer   Send unread alert reminders
argus-cleanup-old-leads.timer  Delete old inactive lead branches
argus-auto-deploy.timer        Pull/deploy new commits from GitHub
argus-backup-db.timer          Create PostgreSQL backups
argus-sync-db-to-neon.timer    Synchronize the primary database to remote backup
argus-health-monitor.timer     Monitor production health and notify Telegram
```

Quick timer check:

```bash
systemctl list-timers --all | grep argus
```

Useful timer status checks:

```bash
systemctl status argus-check-gmail.timer --no-pager -l
systemctl status argus-unread-reminders.timer --no-pager -l
systemctl status argus-cleanup-old-leads.timer --no-pager -l
systemctl status argus-auto-deploy.timer --no-pager -l
systemctl status argus-backup-db.timer --no-pager -l
systemctl status argus-sync-db-to-neon.timer --no-pager -l
systemctl status argus-health-monitor.timer --no-pager -l
```

Useful timer service logs:

```bash
sudo journalctl -u argus-check-gmail.service -n 80 --no-pager -l
sudo journalctl -u argus-unread-reminders.service -n 80 --no-pager -l
sudo journalctl -u argus-cleanup-old-leads.service -n 80 --no-pager -l
sudo journalctl -u argus-auto-deploy.service -n 100 --no-pager -l
sudo journalctl -u argus-backup-db.service -n 80 --no-pager -l
sudo journalctl -u argus-sync-db-to-neon.service -n 80 --no-pager -l
sudo journalctl -u argus-health-monitor.service -n 80 --no-pager -l
```

## Auto Deploy

`argus-auto-deploy.sh` is the production GitHub deploy helper. The systemd unit runs `/usr/local/bin/argus-auto-deploy.sh` under a `flock` lock.

Default behavior:

- uses `/opt/argus` as `PROJECT_DIR`;
- tracks the current local branch unless `DEPLOY_BRANCH` is set;
- refuses to deploy when the working tree is dirty;
- fetches `origin/$DEPLOY_BRANCH`;
- resets hard to the new remote revision when updates exist;
- runs `poetry install --only main` when `pyproject.toml` or `poetry.lock` changed;
- runs migrations, collectstatic, and Django deploy checks;
- restarts `argus-web.service` and `argus-telegram-bot.service`;
- runs doctor unless ops files changed and were not auto-installed.

Operational files are intentionally not auto-installed by default. If files under `deploy/systemd/`, `deploy/scripts/`, `deploy/sudoers/`, or `deploy/install-ops.sh` changed, the script logs that manual install is required:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

Opt-in auto-install is possible with:

```bash
AUTO_INSTALL_OPS=1 /usr/local/bin/argus-auto-deploy.sh
```

Run manually through systemd:

```bash
sudo systemctl start argus-auto-deploy.service
```

Run directly:

```bash
cd /opt/argus
/usr/local/bin/argus-auto-deploy.sh
```

Check the next auto-deploy run:

```bash
systemctl list-timers --all | grep argus-auto-deploy
```

## Installed Helper Scripts

```text
/usr/local/bin/argus-auto-deploy.sh
/usr/local/bin/argus-backup-db.sh
/usr/local/bin/argus-sync-db-to-neon.sh
/usr/local/bin/argus-health-notify.py
/usr/local/bin/argus-doctor.sh
/usr/local/bin/argus-status.sh
```

## Doctor Check

`argus-doctor.sh` is a strict production check. It prints OK/FAIL lines and exits non-zero if Argus is not healthy.

It checks:

- clean git working tree;
- web and Telegram bot services active and enabled;
- all Argus timers active and enabled;
- installed helper scripts are executable;
- installed helper scripts match the repository copies;
- `/health/full/` with `ARGUS_HEALTH_TOKEN` when available, otherwise `/health/`;
- failed systemd units;
- disk usage.

Health checks use retry defaults to avoid false failures during short restarts:

```text
HEALTH_RETRIES=5
HEALTH_RETRY_SLEEP_SECONDS=2
HEALTH_TIMEOUT_SECONDS=8
```

Run manually:

```bash
/usr/local/bin/argus-doctor.sh
```

## Health Monitor Notifications

`argus-health-notify.py` checks:

- `argus-web.service`;
- `argus-telegram-bot.service`;
- all Argus timers;
- `/health/full/` when `ARGUS_HEALTH_TOKEN` is configured, otherwise `/health/`;
- failed systemd units;
- root disk usage.

It sends Telegram only when a new problem appears or when the system recovers. The message prefix comes from `ARGUS_ENV_LABEL`, and state is stored in:

```text
/var/tmp/argus-health-state.json
```

Current Telegram monitor style:

```text
[PROD] Argus problem detected
CRITICAL
Status: FAIL

Problems:
- ...

Time: 2026-07-08 21:03:38 CEST
```

```text
[PROD] Argus recovered
OK
Status: RECOVERED

All monitored services and checks are OK.
```

```text
[PROD] Argus monitor test
OK
Status: TEST

Telegram notifications are working.
```

The real Telegram messages include colored status emojis. The examples above keep the documentation text English-only.

Run manually:

```bash
/usr/local/bin/argus-health-notify.py
```

Send a test Telegram notification:

```bash
/usr/local/bin/argus-health-notify.py --test
```

## Database Backup

`argus-backup-db.sh` creates a plain SQL PostgreSQL dump from `DATABASE_URL` in `/opt/argus/.env.local`, compresses it with gzip, validates it, and stores it under:

```text
/opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz
```

Important behavior:

- uses `/usr/lib/postgresql/18/bin/pg_dump` when available, otherwise `pg_dump` from `PATH`;
- writes to a temporary file first;
- refuses empty backups;
- runs `gzip -t` before publishing the backup;
- sets final backup permissions to `600`;
- removes stale temporary files and zero-size backup files;
- keeps backups for `RETENTION_DAYS=14` by default.

Run manually:

```bash
/usr/local/bin/argus-backup-db.sh
```

Validate the newest backup:

```bash
latest="$(ls -1t /opt/argus/backups/db/argus-postgres-*.sql.gz | head -1)"
gzip -t "$latest"
zcat "$latest" | head -40
```

Restore example to a target PostgreSQL URL:

```bash
zcat /opt/argus/backups/db/argus-postgres-YYYYMMDD-HHMMSS.sql.gz | psql "$RESTORE_DATABASE_URL"
```

Detailed restore instructions live in:

```text
deploy/ops-restore.md
```

## Remote Backup Synchronization

`argus-sync-db-to-neon.timer` runs daily at 03:15 with up to 15 minutes of randomized delay. It uses `DATABASE_URL` as the primary local PostgreSQL database and `BACKUP_DATABASE_URL` as a remote PostgreSQL reserve.

The script makes a consistent custom dump, replaces the remote backup in a single transaction, and verifies that both databases have the same `django_migrations` count. The application never connects to `BACKUP_DATABASE_URL` during normal web, Gmail, or Telegram operation.

Use a direct PostgreSQL endpoint for `BACKUP_DATABASE_URL`; pooled endpoints are not suitable for `pg_restore`. Existing deployments that still use the former backup variable continue to work, but should move to `BACKUP_DATABASE_URL` on the next secret rotation.

Run and inspect it manually:

```bash
sudo systemctl start argus-sync-db-to-neon.service
systemctl status argus-sync-db-to-neon.timer --no-pager -l
sudo journalctl -u argus-sync-db-to-neon.service -n 80 --no-pager -l
```

## Status Snapshot

`argus-status.sh` prints a one-shot production snapshot:

- git status and last commits;
- `/health/`;
- web and Telegram bot service status;
- Argus timers;
- failed systemd units;
- disk and memory usage;
- recent web and Telegram logs.

Run manually:

```bash
/usr/local/bin/argus-status.sh
```
