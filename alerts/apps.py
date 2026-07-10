from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alerts"
    verbose_name = _("Mail and leads")

    def ready(self):
        if not settings.DEBUG and not getattr(settings, "GMAIL_OAUTH_TOKEN_FERNET_KEY", "").strip():
            raise ImproperlyConfigured(
                "GMAIL_OAUTH_TOKEN_FERNET_KEY must be configured when DJANGO_DEBUG=False."
            )
