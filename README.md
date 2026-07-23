# Argus

[![CI](https://github.com/p95max/argus/actions/workflows/ci.yml/badge.svg)](https://github.com/p95max/argus/actions/workflows/ci.yml)
[![CodeQL](https://github.com/p95max/argus/actions/workflows/codeql-analysis.yml/badge.svg)](https://github.com/p95max/argus/actions/workflows/codeql-analysis.yml)
[![Coverage](https://codecov.io/gh/p95max/argus/branch/master/graph/badge.svg)](https://codecov.io/gh/p95max/argus)

---

Argus is a Django 6 control panel for Kleinanzeigen mailbox operations. It reads Gmail messages through per-mailbox OAuth, classifies marketplace emails into buyer leads, noise/system messages, and operational service events, sends Telegram notifications, and gives operators both a full Django Admin UI and a compact mobile control panel.

`The project was built as a commissioned internal operations tool.`

## Current Production Shape

- Flexible operational control and monitoring through the Telegram bot, including alerts, mailbox status, health diagnostics, doctor checks, inline lead actions, and queued manual deploys with start/result reporting.
- Serialized systemd job queue runs server-side operational scripts one at a time with global and per-job locks, duplicate-run prevention, bounded queue waiting, deploy/health checks, and Telegram lifecycle notifications.
- `Deployed on a VPS` as an `internal production service`.
- Intentionally `deployed without Docker` to keep RAM, CPU, and disk overhead low on a minimal VPS plan.
- Full Jazzmin Admin at `/control/`.
- Mobile staff panel at `/m/`.
- Public health endpoint at `/health/`.
- Full health endpoint at `/health/full/` for staff users or `Authorization: Bearer $ARGUS_HEALTH_TOKEN`, with database, mailbox, Telegram, Gmail, backup, and systemd timer diagnostics.
- Multiple Gmail mailboxes with per-mailbox OAuth.
- Encrypted Gmail refresh tokens in `MailboxAccount.gmail_oauth_token`.
- Buyer alerts, noise/system alerts, service events, unread reminders, cleanup, and mailbox health tracking.
- PostgreSQL on the VPS as the primary database, with a daily remote PostgreSQL backup synchronization.
- Tests use `config.test_settings` and in-memory SQLite, even when `.env.local` points to PostgreSQL.
- GitHub Actions CI runs tests, migration checks, linting, and coverage enforcement on every push to `master` and every pull request.
- Coverage reports are uploaded to Codecov after CI test runs.
- CodeQL security analysis runs on pushes, pull requests, and a weekly schedule.
- Production systemd operation scripts under `deploy/`. Detailed production operations documentation is in [`docs/production-operations.md`](docs/production-operations.md).

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

Open locally:

```text
http://127.0.0.1:8000/control/
http://127.0.0.1:8000/m/
```

Simple health check:

```powershell
curl http://127.0.0.1:8000/health/
```

Full health with token:

```powershell
curl -H "Authorization: Bearer YOUR_TOKEN" http://127.0.0.1:8000/health/full/
```

`init_dev` creates or updates the local admin user from `DEV_ADMIN_USERNAME`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD`. It also seeds default lead priority/risk rules. Demo alerts are local-only and are added only with `DJANGO_DEBUG=True` and `DEV_SEED_SAMPLE_DATA=True`.

## Environment

For local development, copy `.env.example` to `.env.local` and fill local secrets there. Do not commit `.env.local`.

For the VPS, copy `.env.production.example` to `/opt/argus/.env.local` and fill the production values there. The production file is intentionally separate: it requires the local PostgreSQL primary URL and the remote backup URL. Do not use the local example on the VPS.

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

With `DJANGO_DEBUG=True`, Argus uses SQLite only when `DATABASE_URL` is empty. If `DATABASE_URL` is set, local runtime uses that PostgreSQL database too. The local example intentionally does not contain production backup settings.

Tests are different on purpose: `pytest.ini` points to `config.test_settings`, which overrides the database to in-memory SQLite. This keeps `python -m poetry run pytest` away from production databases.

## Language And Localization

Argus is an internal operations service, so it intentionally uses one global language for the whole installation instead of per-user language switching. English is the source/default interface language, and Django i18n is enabled for English (`en`), German (`de`), and Russian (`ru`).

The global language applies to:

- Django/Jazzmin Admin at `/control/`.
- Mobile staff panel at `/m/`.
- Telegram bot messages, command replies, inline buttons, health reports, and unread reminder reports.
- Operational labels such as statuses, priorities, mailbox state, and service events.

There is no public language switcher in `/m/`, Telegram, or the operator UI. The superuser-owner chooses the service language in Django Admin:

```text
/control/ -> Mail and leads -> Argus settings -> Interface language
```

Only superusers can view or edit `Argus settings`.

Saving a new language also republishes the native Telegram command-menu descriptions through the Bot API. Existing Telegram messages are immutable, so only newly sent alerts, reports, and command responses use the new language.

## Database

Fresh PostgreSQL setup:

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

There is no SQLite-to-PostgreSQL migration script. New databases are initialized from Django migrations plus `init_dev`.

### Production Backup Topology

Production Django uses the local VPS PostgreSQL instance from `DATABASE_URL`. A separate `BACKUP_DATABASE_URL` points to a remote PostgreSQL reserve and is never used by the application itself.

`argus-sync-db-to-neon.timer` starts daily at 03:15 with a randomized delay of up to 15 minutes. It replaces the remote backup from a consistent local dump, validates it, and compares the `django_migrations` count between both databases. The target is therefore normally no more than about one day behind the primary database.

The first production synchronization completed successfully with `django_migrations=37`; this number will increase as new migrations are added. `ARGUS DOCTOR` and Telegram `/health` show the local archive and remote-copy result, their timer state, and the last run time.

Run or inspect the synchronization manually:

```bash
sudo systemctl start argus-sync-db-to-neon.service
systemctl status argus-sync-db-to-neon.timer --no-pager -l
sudo journalctl -u argus-sync-db-to-neon.service -n 80 --no-pager -l
```

Treat `BACKUP_DATABASE_URL` as a production secret. Rotate any previously exposed backup database password and update `/opt/argus/.env.local` afterwards.

## CI Quality Gate

GitHub Actions is the required quality gate before merge or deploy. The `CI` workflow runs on every push to `master` and on every pull request.

The workflow enforces:

```powershell
python -m poetry check --lock
python -m poetry run ruff check alerts config tests
python -m poetry run python manage.py makemigrations --check --dry-run
python -m poetry run pytest --cov=alerts --cov=config --cov-report=term-missing --cov-report=xml --cov-fail-under=80
```

A change should not be merged or deployed unless the GitHub Actions `CI` check is green.

CodeQL runs separately as a lightweight security analysis workflow on pushes, pull requests, and a weekly schedule.

## Deploy Checks

Run production readiness checks before deploy:

```powershell
python -m poetry run python manage.py argus_check_deploy
python -m poetry run python manage.py argus_check_deploy --json
python -m poetry run python manage.py check --deploy --fail-level ERROR
```

The deploy check fails if local demo data leaks into production, including the `local-demo@example.local` mailbox. It also verifies deploy-sensitive settings such as `DEBUG`, `DATABASE_URL`, and `GMAIL_OAUTH_TOKEN_FERNET_KEY`.

Operational warnings for a stale Gmail check or recent Telegram delivery errors are reported as `WARN`, but do not cancel a deploy. This avoids a false failure when `check_gmail` is waiting behind the shared background-job lock. Database, secrets, service, backup, timer, and demo-data failures remain blocking.

## Production Operations

Production runs directly on the VPS without Docker. It uses a Python virtual environment, Gunicorn, and systemd services/timers to reduce overhead on a small VPS plan.

Detailed production services, timers, helper scripts, auto-deploy, backup, doctor, and health monitor documentation is in [`docs/production-operations.md`](docs/production-operations.md).

Quick production check:

```bash
/usr/local/bin/argus-doctor.sh
systemctl list-timers --all | grep argus
```

Install or update production ops files on the VPS:

```bash
cd /opt/argus
./deploy/install-ops.sh
```

Run this command after deploying a change under `deploy/scripts/`, `deploy/systemd/`, `deploy/sudoers/`, or `deploy/install-ops.sh`. `/usr/local/bin` helpers and systemd unit files are intentionally installed separately from the Git working tree; `/doctor` reports `Ops deployment: FAILED` while they differ.

### Health And Doctor

`/health/` is intentionally a minimal process liveness endpoint for uptime monitoring. `/health/full/` and the Telegram `/health` command provide operational diagnostics.

Telegram `/health` shows:

- database, active mailboxes, Telegram configuration and recent delivery errors;
- Gmail check freshness and last successful check;
- local archive and remote-copy backup result, timer state, and last run;
- every production timer with a green `enabled + active` status or a red unhealthy status and its next run;
- open service errors, unread leads, today's events, and bot uptime.

Telegram `/doctor` runs `/usr/local/bin/argus-doctor.sh`. It reports service and timer totals, deployed ops-file consistency, individual server timer states, backup results, failed systemd units, disk usage, and Git synchronization.

Use these commands when doctor reports a failure:

```bash
sudo systemctl --failed --no-pager -l
sudo journalctl -u argus-auto-deploy.service -n 120 --no-pager -l
/usr/local/bin/argus-doctor.sh
```

### Gmail Polling Control

Telegram `/polling` shows and manages the real `argus-check-gmail.timer`
state from systemd, not a database flag. The control intentionally lives only
in Telegram: it runs on the production VPS alongside systemd, whereas the
local Windows interface cannot operate systemd services.

The UI reads:

```bash
systemctl is-enabled argus-check-gmail.timer
systemctl is-active argus-check-gmail.timer
systemctl show argus-check-gmail.timer --property=NextElapseUSecRealtime
systemctl list-timers --all --no-pager | grep argus-check-gmail.timer
systemctl cat argus-check-gmail.timer
```

The start/stop buttons call only predefined systemd commands:

```bash
sudo -n systemctl enable --now argus-check-gmail.timer
sudo -n systemctl disable --now argus-check-gmail.timer
sudo -n systemctl --no-block start argus-check-gmail.service
```

Production sudoers allows the Telegram bot runtime to run those exact commands
without a password. There is no separate `gmail_polling_enabled`
database flag; disabling the timer is the main resource-saving switch because it
prevents scheduled Django startup entirely.

### Background Job Queue

The following systemd jobs share `/tmp/argus-background-jobs.lock` and execute one at a time:

- `argus-check-gmail.service`
- `argus-unread-reminders.service`
- `argus-cleanup-old-leads.service`
- `argus-backup-db.service`
- `argus-sync-db-to-neon.service`
- `argus-auto-deploy.service`

Each job waits for the shared lock for up to 15 minutes. A separate per-job lock prevents duplicate instances of the same task. The web service, Telegram polling service, and health monitor remain independent from this queue.

Inspect queue activity:

```bash
sudo lslocks -o COMMAND,PID,TYPE,MODE,PATH --notruncate | grep argus
sudo journalctl \
  -u argus-check-gmail.service \
  -u argus-unread-reminders.service \
  -u argus-cleanup-old-leads.service \
  -u argus-auto-deploy.service \
  -u argus-backup-db.service \
  -u argus-sync-db-to-neon.service \
  --since today --no-pager | grep 'Queue['
```

### Telegram Bot Commands

| Command | Purpose |
| --- | --- |
| `/help` | Show bot capabilities and the current command list. |
| `/status` | Show Gmail mailbox status and latest checks. |
| `/mailboxes` | Alias for `/status`. |
| `/summary` | Show today's lead summary. |
| `/unread` | Show one report with unread leads. |
| `/polling` | Manage the Gmail polling timer on the production server. |
| `/health` | Show DB, Gmail, Telegram, backup, timer, and service-error health. |
| `/doctor` | Run the production doctor and show systemd services, individual timers, backups, Git, and deploy status. |
| `/deploy` | Queue an immediate production auto-deploy and report queue state, actual start, and final result. |

`/deploy` does not run `git add`, `git commit`, or `git push`. It starts the existing `argus-auto-deploy.service` through the shared queue. The bot immediately reports whether the queue is free or busy, then sends a start notification and one of these final states:

- `UPDATED` — a new commit was deployed.
- `UP TO DATE` — `origin/master` and the local `HEAD` were already equal; services were not redeployed.
- `FAILED` — the deploy command exited with an error.

Deploy readiness prints non-blocking operational issues as `WARN`. A stale Gmail check can occur while it waits for the same serialized queue as auto-deploy; it is visible in the report but does not abort the deployment.

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

When a mailbox is not connected yet, Admin shows a localized message that asks the operator to connect Gmail through OAuth. When reconnecting an existing mailbox, Argus rejects a different Google account and also rejects a Gmail address already used by another mailbox.

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

`MarketplaceAlert` is the central operational record. It stores the mailbox, event classification, alert status, priority, parsing result, listing and buyer data, Gmail identifiers, Telegram delivery state, and operator ownership.

A listing case is grouped by:

```text
mailbox + listing_id
```

Alert event types are:

- `buyer_message`
- `listing_expiring`
- `system_notice`
- `noise`

Operational statuses are:

- `unread`
- `in_work`
- `ignored`
- `archived`

Taking an alert into work records the assigned Django user, a display label, and the assignment time. The Admin close-case action deletes all alerts for the selected `mailbox + listing_id` branch but keeps `ProcessedEmail`, so previously processed Gmail messages do not recreate the deleted case.

Alerts require attention when they are unread, high or urgent priority, parser-problematic, connected to mailbox/service failures, or have Telegram delivery errors.

## Cleanup

Old inactive listing branches can be inspected and deleted with:

```powershell
python -m poetry run python manage.py cleanup_old_leads --days 30 --limit 100 --dry-run
python -m poetry run python manage.py cleanup_old_leads --days 30 --limit 100
```

Cleanup rules:

- cases are grouped by `mailbox + listing_id`;
- branches without a `listing_id` are not selected;
- every alert in the branch must have status `ignored`;
- branches containing `unread`, `in_work`, `archived`, or any other status are not deleted automatically;
- the newest alert update in the branch must be older than the configured cutoff;
- `ProcessedEmail` records remain in the database for Gmail deduplication.

## Anti-Spam And Service Events

Argus separates buyer leads, listing lifecycle events, system/noise mail, and operational service failures.

Noise is exposed through the separate spam/noise Admin view and is not sent to Telegram as a normal buyer lead. An operator can promote a useful noise record back to a buyer message.

`ServiceEvent` records mailbox errors, parser errors, Telegram delivery errors, and recovery events. Repeated failures use a fingerprint and occurrence counter instead of creating unlimited duplicate incidents. Events can be open, recovered, or ignored.

## Telegram Access And Notifications

Telegram configuration is loaded from:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_SEND_ON_GMAIL_CHECK=False
```

Access behavior:

- `TELEGRAM_DEFAULT_CHAT_ID` is automatically added to the allowed-chat set.
- `TELEGRAM_ALLOWED_CHAT_IDS` adds more permitted private chats or groups.
- If there is no default chat and the allowed-chat list is empty, all commands are denied.
- If `TELEGRAM_ALLOWED_USER_IDS` is empty, any user inside an allowed chat can run commands.
- If `TELEGRAM_ALLOWED_USER_IDS` is populated, both the chat ID and user ID must be allowed.
- All current bot commands use the same allowlist; there is no separate manager/admin command role.

For two private Telegram users, configure both IDs in both lists:

```env
TELEGRAM_DEFAULT_CHAT_ID=<YOUR_TELEGRAM_ID>
TELEGRAM_ALLOWED_CHAT_IDS=<YOUR_TELEGRAM_ID>,<MANAGER_TELEGRAM_ID>
TELEGRAM_ALLOWED_USER_IDS=<YOUR_TELEGRAM_ID>,<MANAGER_TELEGRAM_ID>
```

In a one-to-one Telegram conversation, the private `chat_id` normally matches that user's Telegram `user_id`. Group chats are different: when the user allowlist is empty, every member of an allowed group can use the bot commands.

Useful management commands:

```powershell
python -m poetry run python manage.py send_telegram_alert 1
python -m poetry run python manage.py send_telegram_system "Argus is running"
python -m poetry run python manage.py run_telegram_bot
python -m poetry run python manage.py send_unread_reminders --dry-run
```

Inline alert actions update lead status to `in_work`, `unread`, or `ignored`, and the mobile button opens `/m/alerts/<id>/` using `ARGUS_PUBLIC_BASE_URL`.

Quiet hours are configured through `TelegramSettings` in Admin. Normal alerts and reminders are skipped during quiet hours unless urgent alerts are explicitly allowed. Noise alerts are never sent as buyer notifications.

## Admin

Main Admin areas include:

- overview dashboard;
- mailbox configuration, Gmail OAuth, health, and manual checks;
- buyer leads and operational listing events;
- spam and noise messages;
- processed-email deduplication log;
- lead priority and risk rules;
- system/service journal;
- Telegram quiet-hours settings;
- global Argus language settings for superusers.

Admin includes status, priority, and risk badges; an attention-required filter; priority/classification explanations; visible operator ownership; close-case actions; and test Telegram actions.

Mailbox management requires superuser access or explicit add/change/delete permissions for `MailboxAccount`. Staff users can view mailbox operational information according to their Django permissions.

## Mobile Control Panel

`/m/` is a compact staff-only interface using the same Django authentication session and mailbox permission checks as Admin.

It includes:

- mailbox health and manual Gmail checks;
- attention-required, today, and my-in-work views;
- spam/noise view;
- cases grouped by `mailbox + listing_id`;
- service journal;
- alert detail pages and quick status actions;
- operator ownership and priority explanations;
- links to full Admin configuration.

The mobile service journal supports recovering or ignoring open service events and opening the related mailbox.

## Security

- Gmail OAuth refresh tokens are encrypted before storage.
- `GMAIL_OAUTH_TOKEN_FERNET_KEY` must remain stable across deploys, backups, and restores.
- When the Fernet key is empty, local development derives a key from `DJANGO_SECRET_KEY`.
- Admin login uses cache-backed lockout protection.
- Mobile POST redirects validate destination hosts.
- Telegram commands are denied unless the chat passes the configured allowlist.
- `/deploy` can only start the predefined `argus-auto-deploy.service` through a restricted sudoers rule; it cannot execute arbitrary root commands.
- Production credentials and `.env.local` must never be committed.

## Tests

Run the full suite:

```powershell
python -m poetry run pytest
```

Current test behavior:

- `pytest.ini` uses `DJANGO_SETTINGS_MODULE = config.test_settings`.
- Tests force in-memory SQLite and do not use production databases.
- Linux-specific queue tests are skipped on Windows because they require `bash` and `flock`.

Useful focused checks:

```powershell
python -m poetry run ruff check alerts config tests
python -m poetry run python manage.py makemigrations --check --dry-run
python -m poetry run pytest -q tests/test_background_job_queue.py
python -m poetry run pytest -q tests/test_deploy_notifications.py tests/test_telegram_deploy_ops.py tests/test_telegram_help_command.py
```

## Contacts

Author: Maksym Petrykin

Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)

Telegram: [@max_p95](https://t.me/max_p95)
