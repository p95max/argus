# Argus

Argus is a Django monitoring tool for Gmail alerts from Kleinanzeigen. It parses incoming marketplace mail, creates actionable alerts, tracks mailbox/service health, and supports Admin plus Telegram workflows.

## Current Capabilities

- Multiple Gmail mailboxes, each with its own OAuth token and health state.
- Kleinanzeigen email parsing into `MarketplaceAlert` records.
- Dedupe by `ProcessedEmail(mailbox, gmail_message_id)`.
- Alert statuses: `unread`, `in_work`, `ignored`.
- Telegram delivery for alerts, reminders, service events, inline status buttons, `/status`, `/mailboxes`, and `/summary`.
- Quiet hours for Telegram notifications through `TelegramSettings` in Admin.
- Service health events for Gmail, parser, Telegram send failures, and recovery.
- Case cleanup by branch: alerts grouped by `mailbox + listing_id`.

## Local Bootstrap

```bash
poetry install
copy .env.example .env.local
# Windows
python -m poetry run python manage.py migrate
python -m poetry run python manage.py init_dev
python -m poetry run python manage.py runserver
python -m poetry run pytest
```

Health check:

```bash
curl http://127.0.0.1:8000/health/
```

The Django Admin URL is configured with `DJANGO_ADMIN_URL` and defaults to `/control/`.

For local development, `init_dev` creates or updates a single admin user from `DEV_ADMIN_USERNAME`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD`. It is idempotent, seeds starter lead flags/demo alerts, and only runs with `DEBUG=True`.

## Environment

Copy `.env.example` to `.env.local` and fill the values that match your setup.

Important settings:

```env
DJANGO_SECRET_KEY=change-me-in-local-env
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_ADMIN_URL=control

GOOGLE_CLIENT_SECRETS_FILE=secrets/google/credentials.json
GOOGLE_OAUTH_REDIRECT_URI=

TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_SEND_ON_GMAIL_CHECK=False
```

Local development uses SQLite when `DJANGO_DEBUG=True`. Production requires `DATABASE_URL` with PostgreSQL when `DJANGO_DEBUG=False`.

For local non-HTTPS OAuth testing, set `OAUTHLIB_INSECURE_TRANSPORT=True`.

## Gmail Flow

1. Put the Google OAuth client secrets file at `GOOGLE_CLIENT_SECRETS_FILE`.
2. Create a `MailboxAccount` in Admin.
3. Open the mailbox page and use the Gmail OAuth action.
4. Use "Check updates" in Admin or run `check_gmail`.

Manual check for all active mailboxes:

```bash
poetry run python manage.py check_gmail --max-results 25
```

Manual check for one mailbox:

```bash
poetry run python manage.py check_gmail --mailbox email@example.com --max-results 25
```

`check_gmail` checks active mailboxes, skips already processed Gmail message IDs, creates alerts, updates mailbox health fields, and records service events on failures. If one mailbox fails, the command logs the error and continues with the rest.

For production, run `check_gmail` from an external scheduler, for example every 5 minutes.

Legacy local OAuth through `connect_gmail` and `GOOGLE_TOKEN_FILE` is still available for debugging, but the main flow is per-mailbox OAuth from Admin.

## Alerts And Cases

`MarketplaceAlert` is the main operational record. Alerts belong to a mailbox and may have a `listing_id`. A case branch is treated as:

```text
mailbox + listing_id
```

Use the Admin action "Кейс закрыт: удалить обращения по listing_id" to manually close a case. It deletes alerts for the selected branch, but keeps `ProcessedEmail` records so old Gmail messages do not recreate alerts later.

## Cleanup

Old inactive branches can be cleaned automatically:

```bash
poetry run python manage.py cleanup_old_leads --days 30 --limit 100 --dry-run
poetry run python manage.py cleanup_old_leads --days 30 --limit 100
```

Cleanup rules:

- Deletes only branches grouped by `mailbox + listing_id`.
- Deletes only old inactive branches.
- A branch is inactive only when all its alerts are `ignored`.
- Branches with any `unread` or `in_work` alert are never deleted by automatic cleanup.
- `ProcessedEmail` is not deleted, because it is required for dedupe.

## Telegram

Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, and `TELEGRAM_ALLOWED_CHAT_IDS`.

Send one existing alert manually:

```bash
poetry run python manage.py send_telegram_alert 1
```

Send an operational message:

```bash
poetry run python manage.py send_telegram_system "Argus is running"
```

Run the Telegram bot for inline buttons and commands:

```bash
poetry run python manage.py run_telegram_bot
```

Supported bot commands:

- `/status`
- `/mailboxes`
- `/summary`

Inline alert actions:

- `in_work`
- `unread`
- `ignored`
- `status`

Automatic Telegram sending from Gmail checks is off by default. Enable it with:

```env
TELEGRAM_SEND_ON_GMAIL_CHECK=True
```

Unread reminders:

```bash
poetry run python manage.py send_unread_reminders --dry-run
poetry run python manage.py send_unread_reminders --min-age-minutes 30 --reminder-interval-minutes 60 --limit 25
```

Quiet hours are configured in Admin through `TelegramSettings`. Normal alerts and reminders are skipped during quiet hours unless the alert is urgent and `allow_urgent_during_quiet_hours` is enabled. Noise alerts are never sent.

## Admin

Main Admin models:

- `Почтовые ящики`: mailbox config, Gmail OAuth, health, manual check.
- `Обращения`: parsed lead/event, status, priority, Telegram delivery fields.
- `Спам и рассылки`: separate Admin view for promotional/system noise that may still be worth reviewing.
- `Проверенные письма`: dedupe log; read-only for normal users.
- `Приоритеты обращений`: classification flags.
- `Журнал системы`: operational health events.
- `Настройки Telegram`: quiet hours.

Mailbox management requires superuser access or add/change/delete permissions for `MailboxAccount`. Staff users can view mailbox operations.

## Tests

Run the test suite:

```bash
poetry run pytest
```

Useful focused checks:

```bash
poetry run pytest tests/test_cleanup.py tests/test_gmail.py tests/test_quiet_hours.py tests/test_unread_reminders.py
poetry run python manage.py makemigrations --check --dry-run
poetry run ruff check alerts
```

On restricted Windows environments, pytest may need a writable temp/cache location.
