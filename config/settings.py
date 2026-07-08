from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from .jazzmin import JAZZMIN_SETTINGS, JAZZMIN_UI_TWEAKS


# =============================================================================
# Paths
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# Environment
# =============================================================================

env = environ.Env(
    DJANGO_DEBUG=(bool, True),
    DJANGO_ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_ADMIN_URL=(str, "control"),
    ARGUS_PUBLIC_BASE_URL=(str, "http://127.0.0.1:8000"),
    DJANGO_TIME_ZONE=(str, "Europe/Berlin"),
    DJANGO_SECURE_SSL_REDIRECT=(bool, False),
    DJANGO_SESSION_COOKIE_SECURE=(bool, False),
    DJANGO_CSRF_COOKIE_SECURE=(bool, False),
    DJANGO_USE_X_FORWARDED_PROTO=(bool, False),
    DJANGO_SECURE_HSTS_SECONDS=(int, 0),
    GMAIL_CHECK_MAX_RESULTS=(int, 25),
    GMAIL_CHECK_FAIL_ON_ERROR=(bool, False),
    GMAIL_OAUTH_TOKEN_FERNET_KEY=(str, ""),
    ADMIN_LOGIN_FAILURE_LIMIT=(int, 5),
    ADMIN_LOGIN_LOCKOUT_SECONDS=(int, 15 * 60),
    TELEGRAM_SEND_ON_GMAIL_CHECK=(bool, False),
    ARGUS_GMAIL_CHECK_STALE_MINUTES=(int, 15),
    ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS=(int, 10 * 60),
    ARGUS_HEALTH_TOKEN=(str, ""),
    DATABASE_CONN_MAX_AGE=(int, 60),
    DATABASE_CONN_HEALTH_CHECKS=(bool, True),
)

environ.Env.read_env(BASE_DIR / ".env", overwrite=False)
environ.Env.read_env(BASE_DIR / ".env.local", overwrite=True)


def normalize_url_path(value: str, default: str) -> str:
    cleaned = (value or default).strip().strip("/")
    return cleaned or default.strip("/")


def require_production_value(name: str, value: str) -> None:
    if not value:
        raise ImproperlyConfigured(f"{name} must be configured when DJANGO_DEBUG=False.")


# =============================================================================
# Core security
# =============================================================================

DEBUG = env.bool("DJANGO_DEBUG")

DEFAULT_DEV_SECRET_KEY = "django-insecure-local-dev-only-change-me"
SECRET_KEY = env.str("DJANGO_SECRET_KEY", default=DEFAULT_DEV_SECRET_KEY)

if not DEBUG and SECRET_KEY == DEFAULT_DEV_SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be configured when DJANGO_DEBUG=False.")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be configured when DJANGO_DEBUG=False.")

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env.bool("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG)

SECURE_HSTS_SECONDS = env.int(
    "DJANGO_SECURE_HSTS_SECONDS",
    default=0 if DEBUG else 60 * 60 * 24 * 30,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=False,
)
SECURE_HSTS_PRELOAD = env.bool(
    "DJANGO_SECURE_HSTS_PRELOAD",
    default=False,
)

if env.bool("DJANGO_USE_X_FORWARDED_PROTO", default=not DEBUG):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# =============================================================================
# Project runtime settings
# =============================================================================

DJANGO_ADMIN_URL = normalize_url_path(
    env.str("DJANGO_ADMIN_URL"),
    default="control",
)
LOGIN_URL = f"/{DJANGO_ADMIN_URL}/login/"
ARGUS_PUBLIC_BASE_URL = env.str("ARGUS_PUBLIC_BASE_URL").strip().rstrip("/")

GMAIL_CHECK_MAX_RESULTS = env.int("GMAIL_CHECK_MAX_RESULTS")
GMAIL_CHECK_FAIL_ON_ERROR = env.bool("GMAIL_CHECK_FAIL_ON_ERROR")
GMAIL_OAUTH_TOKEN_FERNET_KEY = env.str("GMAIL_OAUTH_TOKEN_FERNET_KEY").strip()
ADMIN_LOGIN_FAILURE_LIMIT = env.int("ADMIN_LOGIN_FAILURE_LIMIT")
ADMIN_LOGIN_LOCKOUT_SECONDS = env.int("ADMIN_LOGIN_LOCKOUT_SECONDS")

GOOGLE_OAUTH_REDIRECT_URI = env.str("GOOGLE_OAUTH_REDIRECT_URI", default="")

TELEGRAM_BOT_TOKEN = env.str("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_DEFAULT_CHAT_ID = env.str("TELEGRAM_DEFAULT_CHAT_ID", default="")
TELEGRAM_ALLOWED_CHAT_IDS = env.list("TELEGRAM_ALLOWED_CHAT_IDS", default=[])
TELEGRAM_ALLOWED_USER_IDS = env.list("TELEGRAM_ALLOWED_USER_IDS", default=[])
TELEGRAM_SEND_ON_GMAIL_CHECK = env.bool("TELEGRAM_SEND_ON_GMAIL_CHECK")
ARGUS_GMAIL_CHECK_STALE_MINUTES = env.int("ARGUS_GMAIL_CHECK_STALE_MINUTES")
ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS = env.int("ARGUS_COMMAND_LOCK_TIMEOUT_SECONDS")
ARGUS_HEALTH_TOKEN = env.str("ARGUS_HEALTH_TOKEN").strip()

GOOGLE_CLIENT_SECRETS_FILE = env.str(
    "GOOGLE_CLIENT_SECRETS_FILE",
    default="secrets/google/credentials.json",
)
GOOGLE_TOKEN_FILE = env.str(
    "GOOGLE_TOKEN_FILE",
    default="secrets/google/token.json",
)

if DEBUG and env.bool("OAUTHLIB_INSECURE_TRANSPORT", default=False):
    import os

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


# =============================================================================
# Django apps
# =============================================================================

INSTALLED_APPS = [
    "jazzmin",
    "alerts.apps.AlertsConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]


# =============================================================================
# Middleware
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "alerts.security.AdminLoginRateLimitMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =============================================================================
# URLs / WSGI / Templates
# =============================================================================

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]


# =============================================================================
# Database
# =============================================================================

DATABASE_URL = env.str("DATABASE_URL", default="").strip()
DATABASE_CONN_MAX_AGE = env.int("DATABASE_CONN_MAX_AGE", default=60)
DATABASE_CONN_HEALTH_CHECKS = env.bool("DATABASE_CONN_HEALTH_CHECKS", default=True)

if DEBUG:
    if DATABASE_URL:
        DATABASES = {
            "default": env.db_url_config(DATABASE_URL),
        }
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
else:
    if not DATABASE_URL:
        raise ImproperlyConfigured(
            "DATABASE_URL must be configured when DJANGO_DEBUG=False."
        )

    DATABASES = {
        "default": env.db_url_config(DATABASE_URL),
    }

    DATABASES["default"]["CONN_MAX_AGE"] = DATABASE_CONN_MAX_AGE
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = DATABASE_CONN_HEALTH_CHECKS


# =============================================================================
# Password validation
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# =============================================================================
# Internationalization
# =============================================================================

LANGUAGE_CODE = "ru"
TIME_ZONE = env.str("DJANGO_TIME_ZONE")

USE_I18N = True
USE_TZ = True

# =============================================================================
# Static files
# =============================================================================

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]


# =============================================================================
# Django defaults
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# Logging
# =============================================================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        "alerts": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
