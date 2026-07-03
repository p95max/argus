# Argus

Argus is a Django-based monitoring tool for Gmail alerts from Kleinanzeigen, with Admin and Telegram workflows planned in the roadmap.

## Local bootstrap

```bash
poetry install
copy .env.example .env.local
poetry run python manage.py migrate
poetry run python manage.py runserver
```

Health check:

```bash
curl http://127.0.0.1:8000/health/
```

The Django Admin URL is configured with `DJANGO_ADMIN_URL` and defaults to `/control/`.
