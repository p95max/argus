# Argus

[![CI](https://github.com/p95max/argus/actions/workflows/ci.yml/badge.svg)](https://github.com/p95max/argus/actions/workflows/ci.yml)

Argus is a Django 6 control panel for Kleinanzeigen mailbox operations. It reads Gmail messages through per-mailbox OAuth, classifies marketplace emails into buyer leads, noise/system messages, and operational service events, sends Telegram notifications, and gives operators both a full Django Admin UI and a compact mobile control panel.

`The project was built as a commissioned internal operations tool.`

## Current Production Shape

- `Deployed on a VPS` as an `internal production service`.
- Intentionally `deployed without Docker` to keep RAM, CPU, and disk overhead low on a minimal VPS plan.
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
- GitHub Actions CI runs tests, migration checks, and linting on every push to `master` and every pull request.
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

## CI Quality Gate

GitHub Actions is the required quality gate before merge or deploy. The `CI` workflow runs on every push to `master` and on every pull request.

The workflow enforces:

```powershell
python -m poetry check --lock
python -m poetry run ruff check alerts config tests
python -m poetry run python manage.py makemigrations --check --dry-run
python -m poetry run pytest --cov=alerts --cov=config --cov-report=term-missing
```

A change should not be merged or deployed unless the GitHub Actions `CI` check is green.

## Deploy Checks

Run production readiness checks before deploy:

```powershell
python -m poetry run python manage.py argus_check_deploy
python -m poetry run python manage.py argus_check_deploy --json
python -m poetry run python manage.py check --deploy --fail-level ERROR
```

The deploy check fails if local demo data leaks into production, including the `local-demo@example.local` mailbox. It also verifies deploy-sensitive settings such as `DEBUG`, `DATABASE_URL`, and `GMAIL_OAUTH_TOKEN_FERNET_KEY`.

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
