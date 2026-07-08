# Argus

Argus is a Django control panel for Gmail alerts from Kleinanzeigen. It parses marketplace emails, separates buyer leads from noise/system events, sends Telegram notifications, tracks mailbox health, and gives operators both a full Admin UI and a compact mobile panel.

## Current State

- Full Django/Jazzmin Admin at `/control/`.
- Mobile staff panel at `/m/`.
- Multiple Gmail mailboxes with per-mailbox OAuth.
- Encrypted Gmail refresh tokens in `MailboxAccount.gmail_oauth_token`.
- Buyer alerts, operational events, spam/noise, unread reminders, and cleanup.
- Telegram bot with inline status buttons and an "Open Mobile" link.
- Hosted PostgreSQL/Neon support through `DATABASE_URL`.
- Tests always use local in-memory SQLite through `config.test_settings`, even when `.env.local` points to Neon.

## Local Bootstrap

```powershell
python -m poetry install
copy .env.example .env.local
python -m poetry run python manage.py migrate
python -m poetry run python manage.py init_dev
python -m poetry run python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/control/
http://127.0.0.1:8000/m/
```

Health check:

```powershell
curl http://127.0.0.1:8000/health/
```

Full operational health is available for staff users or with `Authorization: Bearer $ARGUS_HEALTH_TOKEN`:

```text
GET /health/full/
```

It checks database access, active mailboxes, Telegram config, Gmail check freshness, and open service errors.

`init_dev` creates or updates the local admin user from `DEV_ADMIN_USERNAME`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD`. It also seeds default lead priority/risk rules. Demo alerts are local-only and are added only with `DJANGO_DEBUG=True` and `DEV_SEED_SAMPLE_DATA=True`.

## Environment

Copy `.env.example` to `.env.local` and fill local secrets there. Do not commit `.env.local`.

Important settings:

```env
DJANGO_SECRET_KEY=change-me-in-local-env
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_ADMIN_URL=control
ARGUS_PUBLIC_BASE_URL=http://127.0.0.1:8000
ARGUS_ENV_LABEL=LOCAL
ARGUS_HEALTH_TOKEN=
ARGUS_GMAIL_CHECK_STALE_MINUTES=15
ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS=600

DATABASE_URL=
DATABASE_CONN_MAX_AGE=60
DATABASE_CONN_HEALTH_CHECKS=True

ADMIN_LOGIN_FAILURE_LIMIT=5
ADMIN_LOGIN_LOCKOUT_SECONDS=900

GOOGLE_CLIENT_SECRETS_FILE=secrets/google/credentials.json
GOOGLE_OAUTH_REDIRECT_URI=
GMAIL_OAUTH_TOKEN_FERNET_KEY=

TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_SEND_ON_GMAIL_CHECK=False
```

With `DJANGO_DEBUG=True`, Argus uses SQLite only when `DATABASE_URL` is empty. If `DATABASE_URL` is set, local runtime uses that PostgreSQL database too, including Neon.

Tests are different on purpose: `pytest.ini` points to `config.test_settings`, which overrides the database to in-memory SQLite. This keeps `python -m poetry run pytest` away from Neon.

## Database

Fresh PostgreSQL/Neon setup:

```powershell
python -m poetry run python manage.py migrate
python -m poetry run python manage.py init_dev
```

Quick SQL checks in Neon:

```sql
select current_database(), current_user, version();
select count(*) as users_count from auth_user;
select count(*) as lead_flags_count from alerts_leadflag;
select count(*) as mailboxes_count from alerts_mailboxaccount;
select count(*) as alerts_count from alerts_marketplacealert;
```

After `init_dev` on a clean database, the expected starter data is:

```text
users_count = 1
lead_flags_count = 13
mailboxes_count = 1 if DEV_SEED_SAMPLE_DATA=True
alerts_count = 3 if DEV_SEED_SAMPLE_DATA=True
```

There is no SQLite-to-Postgres migration script in the current project state. New cloud databases are initialized from Django migrations plus `init_dev`.

## Deploy Checks

Run the production readiness check before deploy:

```powershell
python -m poetry run python manage.py argus_check_deploy
python -m poetry run python manage.py argus_check_deploy --json
```

The deploy check fails if local demo data leaks into production, including the `local-demo@example.local` mailbox.

The command reuses the full health checks and also verifies deploy-sensitive settings such as `DEBUG`, `DATABASE_URL`, and `GMAIL_OAUTH_TOKEN_FERNET_KEY`.

## Production Timers

Argus uses systemd timers on the VPS for background jobs.

Timer templates live in `deploy/systemd/`. Install or update them on the server with:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

If `deploy/scripts` is missing on the server, pull or deploy the latest repository version first.

### Gmail Check Timer

Purpose: checks Gmail and creates new alerts.

Timer:

```bash
systemctl status argus-check-gmail.timer --no-pager -l
```

Service:

```bash
systemctl status argus-check-gmail.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u argus-check-gmail.service -n 80 --no-pager -l
```

Run manually through systemd:

```bash
sudo systemctl start argus-check-gmail.service
```

Run directly through Django:

```bash
cd /opt/argus
source .venv/bin/activate
python manage.py check_gmail --max-results 25
```

### Unread Reminders Timer

Purpose: sends Telegram reminders for unread alerts.

Timer:

```bash
systemctl status argus-unread-reminders.timer --no-pager -l
```

Service:

```bash
systemctl status argus-unread-reminders.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u argus-unread-reminders.service -n 80 --no-pager -l
```

Run manually through systemd:

```bash
sudo systemctl start argus-unread-reminders.service
```

Run directly through Django:

```bash
cd /opt/argus
source .venv/bin/activate
python manage.py send_unread_reminders --min-age-minutes 30 --reminder-interval-minutes 60 --limit 25
```

### Cleanup Old Leads Timer

Purpose: removes old inactive lead branches.

Timer:

```bash
systemctl status argus-cleanup-old-leads.timer --no-pager -l
```

Service:

```bash
systemctl status argus-cleanup-old-leads.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u argus-cleanup-old-leads.service -n 80 --no-pager -l
```

Run real cleanup through systemd:

```bash
sudo systemctl start argus-cleanup-old-leads.service
```

Safe dry run:

```bash
cd /opt/argus
source .venv/bin/activate
python manage.py cleanup_old_leads --days 30 --limit 100 --dry-run
```

### Auto Deploy Timer

Purpose: checks GitHub once per hour and pulls new commits.

Timer:

```bash
systemctl status argus-auto-deploy.timer --no-pager -l
```

Service:

```bash
systemctl status argus-auto-deploy.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u argus-auto-deploy.service -n 100 --no-pager -l
```

Run auto deploy manually through systemd:

```bash
sudo systemctl start argus-auto-deploy.service
```

Run deploy script manually:

```bash
cd /opt/argus
./deploy.sh
```

Check the next run:

```bash
systemctl list-timers --all | grep argus-auto
```

### Backup Timer

Purpose: creates a daily PostgreSQL dump before cleanup runs.

Timer:

```bash
systemctl status argus-backup-db.timer --no-pager -l
```

Service:

```bash
systemctl status argus-backup-db.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u argus-backup-db.service -n 80 --no-pager -l
```

Run manually through systemd:

```bash
sudo systemctl start argus-backup-db.service
```

### Health Monitor Timer

Purpose: checks Argus health and sends an operational notification when needed.

Timer:

```bash
systemctl status argus-health-monitor.timer --no-pager -l
```

Service:

```bash
systemctl status argus-health-monitor.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u argus-health-monitor.service -n 80 --no-pager -l
```

Run manually through systemd:

```bash
sudo systemctl start argus-health-monitor.service
```

The current service expects `/usr/local/bin/argus-health-notify.py` to exist on the server.

### Timer Quick Checks

Check all timers:

```bash
systemctl status argus-check-gmail.timer --no-pager -l
systemctl status argus-unread-reminders.timer --no-pager -l
systemctl status argus-cleanup-old-leads.timer --no-pager -l
systemctl status argus-auto-deploy.timer --no-pager -l
systemctl status argus-backup-db.timer --no-pager -l
systemctl status argus-health-monitor.timer --no-pager -l
```

Check all timer service logs:

```bash
sudo journalctl -u argus-check-gmail.service -n 40 --no-pager -l
sudo journalctl -u argus-unread-reminders.service -n 40 --no-pager -l
sudo journalctl -u argus-cleanup-old-leads.service -n 40 --no-pager -l
sudo journalctl -u argus-auto-deploy.service -n 40 --no-pager -l
sudo journalctl -u argus-backup-db.service -n 40 --no-pager -l
sudo journalctl -u argus-health-monitor.service -n 40 --no-pager -l
```

## Production Scripts

Production helper scripts live in `deploy/scripts/` and are installed into `/usr/local/bin/`.

### Database Backup

`argus-backup-db.sh` creates a PostgreSQL custom-format dump from `DATABASE_URL` in `/opt/argus/.env.local`, stores it in `/opt/argus/backups`, restricts file permissions, and deletes dumps older than 14 days.

Run manually:

```bash
sudo /usr/local/bin/argus-backup-db.sh
```

Restore example:

```bash
pg_restore --clean --if-exists --no-owner --no-privileges --dbname "$DATABASE_URL" /opt/argus/backups/argus-db-YYYYMMDD-HHMMSS.dump
```

### Health Notify

`argus-health-notify.py` checks:

- `argus-web.service`
- `argus-telegram-bot.service`
- Argus timers
- `/health/full/` when `ARGUS_HEALTH_TOKEN` is configured, otherwise `/health/`
- failed systemd units
- root disk usage

It sends Telegram only when a new problem appears or when the system recovers. The message prefix comes from `ARGUS_ENV_LABEL`, and state is stored in `/var/tmp/argus-health-state.json`.

Run manually:

```bash
sudo /usr/local/bin/argus-health-notify.py
```

Send a test Telegram notification:

```bash
sudo /usr/local/bin/argus-health-notify.py --test
```

### Status Snapshot

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
sudo /usr/local/bin/argus-status.sh
```

### Doctor Check

`argus-doctor.sh` is a strict automation check. It prints OK/FAIL lines and exits non-zero if Argus is not healthy.

It checks:

- clean git working tree;
- web and Telegram bot services;
- all Argus timers, including backup and health monitor;
- `/health/full/` with `ARGUS_HEALTH_TOKEN` when available;
- failed systemd units;
- disk usage.

Run manually:

```bash
sudo /usr/local/bin/argus-doctor.sh
```

## Security

- Gmail OAuth refresh tokens are encrypted before being stored.
- Migration `0012_encrypt_gmail_oauth_tokens` encrypts older plaintext mailbox tokens.
- Set `GMAIL_OAUTH_TOKEN_FERNET_KEY` explicitly for production and keep it stable across deploys, backups, and restores.
- If `GMAIL_OAUTH_TOKEN_FERNET_KEY` is empty, Argus derives a local Fernet key from `DJANGO_SECRET_KEY`.
- Admin login has cache-backed lockout by IP plus username.
- Mobile POST redirects validate `next` against the current host.
- Telegram async sending uses async-safe ORM calls.
- Private mailbox connection data is not shown after save.

## Gmail Flow

1. Put Google OAuth client secrets at `GOOGLE_CLIENT_SECRETS_FILE`.
2. Create a `MailboxAccount` in Admin with only a human-readable name.
3. Open the mailbox in Admin and use the Gmail connect action.
4. Argus reads the Gmail address from Google OAuth and fills the mailbox email automatically.
5. Run a manual check from Admin, Mobile, or the command line.

Recommended local OAuth callback:

```env
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/control/alerts/mailboxaccount/oauth/callback/
```

Add the same URL in Google Cloud Console under "Authorized redirect URIs". Keep the browser host identical: `localhost` and `127.0.0.1` are different OAuth redirect URIs.

If a mailbox is not connected yet, Admin shows `Email ещё не подключен. Подключите Gmail через OAuth.` instead of an empty email. When reconnecting an existing mailbox, Argus rejects a different Google account and also rejects a Gmail address already used by another mailbox.

Manual checks:

```powershell
python -m poetry run python manage.py check_gmail --max-results 25
python -m poetry run python manage.py check_gmail --mailbox email@example.com --max-results 25
```

`check_gmail` checks active mailboxes, skips already processed Gmail message IDs, creates alerts, updates mailbox health, records service events on failures, and continues if one mailbox fails.

`check_gmail` is protected by an atomic file lock in `tmp/command_locks` (`ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS`) so overlapping timers do not run the same command concurrently. `cleanup_old_leads` uses the same lock pattern.

## Alerts And Cases

`MarketplaceAlert` is the main operational record. A branch/case is grouped by:

```text
mailbox + listing_id
```

Admin action:

```text
Кейс закрыт: удалить обращения по listing_id
```

It deletes alerts for the selected branch but keeps `ProcessedEmail`, so old Gmail messages do not recreate alerts after the branch was removed.

Alerts are treated as "Требует внимания" when they are unread, high/urgent, parser-problematic, linked to a mailbox error, or have Telegram delivery errors.

## Cleanup

Automatic cleanup:

```powershell
python -m poetry run python manage.py cleanup_old_leads --days 30 --limit 100 --dry-run
python -m poetry run python manage.py cleanup_old_leads --days 30 --limit 100
```

Rules:

- Deletes only branches grouped by `mailbox + listing_id`.
- Deletes only old inactive branches.
- A branch is inactive only when all its alerts are `ignored`.
- Branches with any `unread` or `in_work` alert are never deleted automatically.
- `ProcessedEmail` is kept for dedupe.

## Anti-Spam And Events

Argus separates:

- buyer messages;
- promotional/system/noise emails;
- operational listing events, for example listing expiration;
- service health events.

Noise is stored separately through the "Спам и рассылки" Admin section and is not sent to Telegram as a normal buyer lead. Useful noise can be promoted back to a buyer message from Admin.

Operational events are kept separate from buyer messages and can still be sent as service/operational notifications where appropriate.

## Telegram

Set:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_ALLOWED_USER_IDS=
```

Commands:

```powershell
python -m poetry run python manage.py send_telegram_alert 1
python -m poetry run python manage.py send_telegram_system "Argus is running"
python -m poetry run python manage.py run_telegram_bot
```

Bot commands:

- `/status`
- `/mailboxes`
- `/summary`
- `/health`

Inline alert actions:

- `in_work`
- `unread`
- `ignored`
- `status`

The "Open Mobile" inline button uses `ARGUS_PUBLIC_BASE_URL` and opens:

```text
/m/alerts/<id>/
```

Automatic Telegram sending from Gmail checks is off by default:

```env
TELEGRAM_SEND_ON_GMAIL_CHECK=False
```

Unread reminders:

```powershell
python -m poetry run python manage.py send_unread_reminders --dry-run
python -m poetry run python manage.py send_unread_reminders --min-age-minutes 30 --reminder-interval-minutes 60 --limit 25
```

Quiet hours are configured in Admin through "Настройки Telegram". Normal alerts and reminders are skipped during quiet hours unless urgent alerts are explicitly allowed. Noise alerts are never sent.

`/health` shows DB/Gmail status, last check time, open errors, unread alerts, and bot uptime.

## Admin

Main sections:

- `Обзор`: dashboard.
- `Почтовые ящики`: mailbox config, Gmail OAuth, health, manual check.
- `Обращения`: buyer leads and operational events.
- `Спам и рассылки`: promotional/system/noise messages.
- `Проверенные письма`: dedupe log, read-only for normal users.
- `Приоритеты обращений`: priority/risk classification rules.
- `Системный журнал`: service events and errors.
- `Настройки Telegram`: quiet hours.

Admin includes status/priority/risk badges, a "Требует внимания" filter, explanation text for priority/flags, visible operator ownership for alerts in work, and a test Telegram alert action.

Mailbox management requires superuser access or explicit add/change/delete permissions for `MailboxAccount`. Staff users can view mailbox operational profile data.

Admin code is split under `alerts/admin_site/`; `alerts/admin.py` only re-exports registrations.

## Mobile Control Panel

`/m/` is a compact staff-only phone panel. It uses the same Django auth/session and the same mailbox permission checks as Admin.

It includes:

- operational Gmail card with status, last check, last success, today's new alerts, and "Проверить сейчас";
- "Требует внимания" default view;
- "Сегодня";
- "Мои в работе";
- "Спам и рассылки";
- "Кейсы" grouped by `mailbox + listing_id` with basic listing analytics;
- "Системный журнал";
- quiet-hours toggle with a link to full Admin settings;
- manual mailbox check button for users with mailbox management permissions;
- alert detail page;
- quick status actions;
- visible operator ownership;
- priority/flag explanation;
- mailbox health;
- links back to full Admin.

The mobile system journal supports operational actions on open service events:

- `Mark recovered`;
- `Ignore this error`;
- `Open related mailbox`.

## Templates And Static

Mobile templates extend the root template:

```text
templates/base.html
```

The base template includes the favicon block. The current favicon is:

```text
static/favicon.svg
```

`/favicon.ico` redirects to the static favicon through `config/urls.py`.

## Tests

Run:

```powershell
python -m poetry run pytest
```

Current test setup:

- `pytest.ini` uses `DJANGO_SETTINGS_MODULE = config.test_settings`.
- `config.test_settings` inherits runtime settings but forces in-memory SQLite.
- Tests do not use Neon, even when `.env.local` contains `DATABASE_URL`.
- Pytest cache is disabled with `-p no:cacheprovider` to avoid restricted Windows cache writes.

Useful focused checks:

```powershell
python -m poetry run pytest tests/test_local_qa_flow.py
python -m poetry run pytest tests/test_cleanup.py tests/test_gmail.py tests/test_quiet_hours.py tests/test_unread_reminders.py
python -m poetry run python manage.py makemigrations --check --dry-run
python -m poetry run ruff check alerts
```

Latest full local result:

```text
109 passed
```

---

## Contacts

Author: Maksym Petrykin

Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)

Telegram: [@max_p95](https://t.me/max_p95)
