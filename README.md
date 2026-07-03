# Argus

Argus is a Django-based monitoring tool for Gmail alerts from Kleinanzeigen, with Admin and Telegram workflows planned in the roadmap.

## Local bootstrap

```bash
poetry install
copy .env.example .env.local
python -m poetry run python manage.py migrate
python -m poetry run python manage.py init_dev
python -m poetry run python manage.py runserver
```

Health check:

```bash
curl http://127.0.0.1:8000/health/
```

The Django Admin URL is configured with `DJANGO_ADMIN_URL` and defaults to `/control/`.
The Admin UI uses Jazzmin with the standard dark `darkly` theme.

For local development, `init_dev` creates or updates a single admin user from
`DEV_ADMIN_USERNAME`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD` in `.env.local`.
The command is idempotent, seeds starter classification flags/demo alerts, and only runs with `DEBUG=True`.

## Gmail MVP

Place your Google OAuth client secrets file at `GOOGLE_CLIENT_SECRETS_FILE`.

```env
GOOGLE_CLIENT_SECRETS_FILE=secrets/google/credentials.json
```

Create a mailbox in Django Admin, then open the mailbox page and click:

```text
Connect / Reconnect
```

Argus stores the OAuth token per `MailboxAccount`, so each mailbox is connected and refreshed independently.

To check Gmail manually for all active mailboxes:

```bash
poetry run python manage.py check_gmail --max-results 25
```

To check one mailbox only:

```bash
poetry run python manage.py check_gmail --mailbox email@example.com --max-results 25
```

`check_gmail` reads active mailboxes, skips already processed Gmail message IDs, creates alerts, and updates mailbox health fields.

For production, run `check_gmail` from an external scheduler, for example a systemd timer every 5 minutes.

Recommended production command:

```bash
python manage.py check_gmail --max-results 25 --fail-on-error
```

Legacy local OAuth through `connect_gmail` and `GOOGLE_TOKEN_FILE` is intended only for local debugging, not as the main production flow.

## Telegram MVP

Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, and `TELEGRAM_ALLOWED_CHAT_IDS` in `.env.local`.
To send one existing alert manually:

```bash
python -m poetry run python manage.py send_telegram_alert 1
```

To send an operational message:

```bash
poetry run python manage.py send_telegram_system "Argus is running"
```

To process inline buttons (`В работу`, `Снять / не в работе`, `Игнор`), run:

```bash
python -m poetry run python manage.py run_telegram_bot
```

Automatic sending from Gmail checks is off by default. Enable it with `TELEGRAM_SEND_ON_GMAIL_CHECK=True`.


python -m poetry run pytest
