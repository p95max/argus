# Argus

Argus is a Django 6 control panel for Kleinanzeigen mailbox operations. It reads Gmail messages through per-mailbox OAuth, classifies marketplace emails into buyer leads, noise/system messages, and operational service events, sends Telegram notifications, and gives operators both a full Django Admin UI and a compact mobile control panel.

## Current Production Shape

- Deployed on a VPS as an internal production service. No public project URL is documented here.
- Full Jazzmin Admin at `/control/`.
- Mobile staff panel at `/m/`.
- Public health endpoint at `/health/`.
- Full health endpoint at `/health/full/` for staff users or `Authorization: Bearer $ARGUS_HEALTH_TOKEN`.
- Multiple Gmail mailboxes with per-mailbox OAuth.
- Encrypted Gmail refresh tokens in `MailboxAccount.gmail_oauth_token`.
- Buyer alerts, noise/system alerts, service events, unread reminders, cleanup, and mailbox health tracking.
- Telegram bot with inline alert actions, status commands, health/doctor commands, and mobile links.
- PostgreSQL/Neon support through `DATABASE_URL`.
- Tests use `config.test_settings` and in-memory SQLite, even when `.env.local` points to PostgreSQL.
- Production systemd operation scripts under `deploy/`.

## Main URLs

```text
/control/                 Full Django/Jazzmin Admin
/m/                       Mobile control panel
/health/                  Simple health JSON
/health/full/             Full operational health JSON
/favicon.ico              Redirects to static/favicon.svg
```

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

Full health with token:

```powershell
curl -H "Authorization: Bearer YOUR_TOKEN" http://127.0.0.1:8000/health/full/
```

`init_dev` creates or updates the local admin user from `DEV_ADMIN_USERNAME`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD`. It also seeds default lead priority/risk rules. Demo alerts are local-only and are added only with `DJANGO_DEBUG=True` and `DEV_SEED_SAMPLE_DATA=True`.

## Environment

Copy `.env.example` to `.env.local` and fill local secrets there. Do not commit `.env.local`.

Important settings:

```env
DJANGO_SECRET_KEY=change-me-in-local-env
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=YOUR-PRODUCTION.com,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=
DJANGO_ADMIN_URL=control
ARGUS_PUBLIC_BASE_URL=http://127.0.0.1:8000
ARGUS_ENV_LABEL=LOCAL
ARGUS_HEALTH_TOKEN=GENERATE-A-SECURE-RANDOM-STRING
ARGUS_GMAIL_CHECK_STALE_MINUTES=15
ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS=600
DJANGO_TIME_ZONE=Europe/Berlin

DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_SESSION_COOKIE_SECURE=False
DJANGO_CSRF_COOKIE_SECURE=False
DJANGO_USE_X_FORWARDED_PROTO=False
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False

DATABASE_URL=
DATABASE_CONN_MAX_AGE=60
DATABASE_CONN_HEALTH_CHECKS=True

DEV_ADMIN_USERNAME=admin
DEV_ADMIN_EMAIL=admin@example.local
DEV_ADMIN_PASSWORD=change-me
DEV_SEED_SAMPLE_DATA=True

GOOGLE_CLIENT_SECRETS_FILE=secrets/google/credentials.json
GOOGLE_TOKEN_FILE=secrets/google/token.json
GOOGLE_OAUTH_REDIRECT_URI=
GMAIL_CHECK_MAX_RESULTS=25
GMAIL_CHECK_FAIL_ON_ERROR=False
GMAIL_OAUTH_TOKEN_FERNET_KEY=

TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_SEND_ON_GMAIL_CHECK=False

OAUTHLIB_INSECURE_TRANSPORT=False
```

With `DJANGO_DEBUG=True`, Argus uses SQLite only when `DATABASE_URL` is empty. If `DATABASE_URL` is set, local runtime uses that PostgreSQL database too, including Neon.

Tests are different on purpose: `pytest.ini` points to `config.test_settings`, which overrides the database to in-memory SQLite. This keeps `python -m poetry run pytest` away from Neon.

## Database

Fresh PostgreSQL/Neon setup:

```powershell
python -m poetry run python manage.py migrate
python -m poetry run python manage.py init_dev
```

Quick SQL checks:

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

There is no SQLite-to-PostgreSQL migration script. New cloud databases are initialized from Django migrations plus `init_dev`.

## Deploy Checks

Run production readiness checks before deploy:

```powershell
python -m poetry run python manage.py argus_check_deploy
python -m poetry run python manage.py argus_check_deploy --json
python -m poetry run python manage.py check --deploy --fail-level ERROR
```

The deploy check fails if local demo data leaks into production, including the `local-demo@example.local` mailbox. It also verifies deploy-sensitive settings such as `DEBUG`, `DATABASE_URL`, and `GMAIL_OAUTH_TOKEN_FERNET_KEY`.

## Production Operations

Production helper scripts live in `deploy/scripts/` and are installed into `/usr/local/bin/`. Systemd unit and timer templates live in `deploy/systemd/` and are installed into `/etc/systemd/system`.

Install or update production ops files on the VPS:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

The installer:

- installs `deploy/systemd/argus-*.service` and `deploy/systemd/argus-*.timer`;
- installs `deploy/scripts/argus-*` to `/usr/local/bin` with group `argus` and mode `0750`;
- reloads systemd;
- enables and starts the web and Telegram bot services;
- enables and starts all Argus timers.

Check production state:

```bash
/usr/local/bin/argus-doctor.sh
systemctl list-timers --all | grep argus
```

## Production Services And Timers

Argus production is managed by these main services:

```text
argus-web.service              Django/Gunicorn web app
argus-telegram-bot.service     Telegram polling bot
```

Background jobs are managed by these timers:

```text
argus-check-gmail.timer        Fetch Gmail and create alerts
argus-unread-reminders.timer   Send unread alert reminders
argus-cleanup-old-leads.timer  Delete old inactive lead branches
argus-auto-deploy.timer        Pull/deploy new commits from GitHub
argus-backup-db.timer          Create PostgreSQL backups
argus-health-monitor.timer     Monitor production health and notify Telegram
```

Quick timer check:

```bash
systemctl list-timers --all | grep argus
```

Useful service checks:

```bash
systemctl status argus-web.service --no-pager -l
systemctl status argus-telegram-bot.service --no-pager -l
systemctl status argus-check-gmail.timer --no-pager -l
systemctl status argus-unread-reminders.timer --no-pager -l
systemctl status argus-cleanup-old-leads.timer --no-pager -l
systemctl status argus-auto-deploy.timer --no-pager -l
systemctl status argus-backup-db.timer --no-pager -l
systemctl status argus-health-monitor.timer --no-pager -l
```

Useful logs:

```bash
sudo journalctl -u argus-web.service -n 100 --no-pager -l
sudo journalctl -u argus-telegram-bot.service -n 100 --no-pager -l
sudo journalctl -u argus-check-gmail.service -n 80 --no-pager -l
sudo journalctl -u argus-unread-reminders.service -n 80 --no-pager -l
sudo journalctl -u argus-cleanup-old-leads.service -n 80 --no-pager -l
sudo journalctl -u argus-auto-deploy.service -n 100 --no-pager -l
sudo journalctl -u argus-backup-db.service -n 80 --no-pager -l
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

Operational files are intentionally not auto-installed by default. If files under `deploy/systemd/`, `deploy/scripts/`, or `deploy/install-ops.sh` changed, the script logs that manual install is required:

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

## Production Helper Scripts

Installed helpers:

```text
/usr/local/bin/argus-auto-deploy.sh
/usr/local/bin/argus-backup-db.sh
/usr/local/bin/argus-health-notify.py
/usr/local/bin/argus-doctor.sh
/usr/local/bin/argus-status.sh
```

### Doctor Check

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

### Health Monitor Notifications

`argus-health-notify.py` checks:

- `argus-web.service`;
- `argus-telegram-bot.service`;
- all Argus timers;
- `/health/full/` when `ARGUS_HEALTH_TOKEN` is configured, otherwise `/health/`;
- failed systemd units;
- root disk usage.

It sends Telegram only when a new problem appears or when the system recovers. The message prefix comes from `ARGUS_ENV_LABEL`, and state is stored in `/var/tmp/argus-health-state.json`.

Current Telegram monitor style:

```text
🔴 [PROD] Argus problem detected
🔴 CRITICAL
Status: FAIL

Problems:
• ...

Time: 2026-07-08 21:03:38 CEST
```

```text
🟢 [PROD] Argus recovered
🟢 OK
Status: RECOVERED

All monitored services and checks are OK.
```

```text
🟢 [PROD] Argus monitor test
🟢 OK
Status: TEST

Telegram notifications are working.
```

Run manually:

```bash
/usr/local/bin/argus-health-notify.py
```

Send a test Telegram notification:

```bash
/usr/local/bin/argus-health-notify.py --test
```

### Database Backup

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

Detailed restore instructions live in `deploy/ops-restore.md`.

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
/usr/local/bin/argus-status.sh
```

## Gmail Flow

1. Put Google OAuth client secrets at `GOOGLE_CLIENT_SECRETS_FILE`.
2. Create a `MailboxAccount` in Admin with only a human-readable name.
3. Open the mailbox in Admin and use the Gmail connect action.
4. Argus reads the Gmail address from Google OAuth and fills the mailbox email automatically.
5. Run a manual check from Admin, Mobile, timer, or command line.

Recommended local OAuth callback:

```env
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/control/alerts/mailboxaccount/oauth/callback/
```

Add the same URL in Google Cloud Console under "Authorized redirect URIs". Keep the browser host identical: `localhost` and `127.0.0.1` are different OAuth redirect URIs.

If a mailbox is not connected yet, Admin shows `Email ещё не подключен. Подключите Gmail через OAuth.` instead of an empty email. When reconnecting an existing mailbox, Argus rejects a different Google account and also rejects a Gmail address already used by another mailbox.

Manual Gmail checks:

```powershell
python -m poetry run python manage.py check_gmail --max-results 25
python -m poetry run python manage.py check_gmail --mailbox email@example.com --max-results 25
```

Production direct run:

```bash
cd /opt/argus
source .venv/bin/activate
python manage.py check_gmail --max-results 25
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

- deletes only branches grouped by `mailbox + listing_id`;
- deletes only old inactive branches;
- a branch is inactive only when all its alerts are `ignored`;
- branches with any `unread` or `in_work` alert are never deleted automatically;
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
TELEGRAM_SEND_ON_GMAIL_CHECK=False
```

Management commands:

```powershell
python -m poetry run python manage.py send_telegram_alert 1
python -m poetry run python manage.py send_telegram_system "Argus is running"
python -m poetry run python manage.py run_telegram_bot
python -m poetry run python manage.py send_unread_reminders --dry-run
```

Bot commands:

```text
/status      Mailbox status
/mailboxes   Alias for /status
/summary     Daily alerts summary
/health      Health summary
/doctor      Runs /usr/local/bin/argus-doctor.sh and appends git deploy status
```

Inline alert actions:

```text
in_work
unread
ignored
status
```

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

## Admin

Main sections:

- `Обзор`: dashboard;
- `Почтовые ящики`: mailbox config, Gmail OAuth, health, manual check;
- `Обращения`: buyer leads and operational events;
- `Спам и рассылки`: promotional/system/noise messages;
- `Проверенные письма`: dedupe log, read-only for normal users;
- `Приоритеты обращений`: priority/risk classification rules;
- `Системный журнал`: service events and errors;
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

## Security

- Gmail OAuth refresh tokens are encrypted before being stored.
- Migration `0012_encrypt_gmail_oauth_tokens` encrypts older plaintext mailbox tokens.
- Set `GMAIL_OAUTH_TOKEN_FERNET_KEY` explicitly for production and keep it stable across deploys, backups, and restores.
- If `GMAIL_OAUTH_TOKEN_FERNET_KEY` is empty, Argus derives a local Fernet key from `DJANGO_SECRET_KEY`.
- Admin login has cache-backed lockout by IP plus username.
- Mobile POST redirects validate `next` against the current host.
- Telegram async sending uses async-safe ORM calls.
- Private mailbox connection data is not shown after save.
- Keep production GitHub tokens out of `origin` URLs and store them only through Git credential helpers when needed.

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

## Contacts

Author: Maksym Petrykin

Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)

Telegram: [@max_p95](https://t.me/max_p95)
