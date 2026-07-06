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

`init_dev` creates or updates the local admin user from `DEV_ADMIN_USERNAME`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD`. It also seeds default lead priority/risk rules. Demo alerts are added when `DEV_SEED_SAMPLE_DATA=True`.

## Environment

Copy `.env.example` to `.env.local` and fill local secrets there. Do not commit `.env.local`.

Important settings:

```env
DJANGO_SECRET_KEY=change-me-in-local-env
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_ADMIN_URL=control
ARGUS_PUBLIC_BASE_URL=http://127.0.0.1:8000

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

- "Требует внимания" default view;
- "Сегодня";
- "Мои в работе";
- "Спам и рассылки";
- "Системный журнал";
- quiet-hours toggle with a link to full Admin settings;
- manual mailbox check button for users with mailbox management permissions;
- alert detail page;
- quick status actions;
- visible operator ownership;
- priority/flag explanation;
- mailbox health;
- links back to full Admin.

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
97 passed
```
