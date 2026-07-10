from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.utils import translation


class AdminSelectedLocaleMiddleware:
    """
    Activate the project language selected by a superuser in Django Admin.

    There is intentionally no public language switcher: Argus uses one global
    operational language for admin, mobile panel, and Telegram-facing views.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language_code = self._get_language_code()
        translation.activate(language_code)
        request.LANGUAGE_CODE = language_code
        response = self.get_response(request)
        response.headers.setdefault("Content-Language", language_code)
        return response

    def _get_language_code(self) -> str:
        from .models import ArgusSettings

        try:
            return ArgusSettings.load().language_code
        except (OperationalError, ProgrammingError):
            return settings.LANGUAGE_CODE
