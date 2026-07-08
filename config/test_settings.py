from .settings import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

ARGUS_PUBLIC_BASE_URL = "http://127.0.0.1:8000"
DJANGO_ADMIN_URL = "control"
LOGIN_URL = "/control/login/"
