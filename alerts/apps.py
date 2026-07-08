from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alerts"
    verbose_name = "Почта и обращения"

    def ready(self):
        if not settings.DEBUG and not getattr(settings, "GMAIL_OAUTH_TOKEN_FERNET_KEY", "").strip():
            raise ImproperlyConfigured(
                "GMAIL_OAUTH_TOKEN_FERNET_KEY must be configured when DJANGO_DEBUG=False."
            )
