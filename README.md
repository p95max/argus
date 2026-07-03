# Argus

Argus is a Django-based monitoring tool for Gmail alerts from Kleinanzeigen, with Admin and Telegram workflows planned in the roadmap.

## Local bootstrap

```bash
poetry install
copy .env.example .env.local
poetry run python manage.py migrate
poetry run python manage.py init_dev
poetry run python manage.py runserver
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

Place your Google OAuth client secrets file at `GOOGLE_CLIENT_SECRETS_FILE`, then run:

```bash
poetry run python manage.py connect_gmail
poetry run python manage.py check_gmail --max-results 10
```

`check_gmail` reads active mailboxes, skips already processed Gmail message IDs, creates alerts, and updates mailbox health fields.
Use `--mailbox email@example.com` to check one mailbox; without it, all active mailboxes are checked.
