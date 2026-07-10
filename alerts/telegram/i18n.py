from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.core.exceptions import SynchronousOnlyOperation
from django.utils import translation
from django.utils.translation import gettext


_telegram_language: ContextVar[str] = ContextVar("telegram_language", default="")


def get_argus_telegram_language() -> str:
    if language := _telegram_language.get():
        return language

    from ..models import ArgusSettings

    try:
        return ArgusSettings.load().language_code
    except (OperationalError, ProgrammingError, RuntimeError, SynchronousOnlyOperation):
        return settings.LANGUAGE_CODE


def use_argus_telegram_language(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with translation.override(get_argus_telegram_language()):
            return func(*args, **kwargs)

    return wrapper


def telegram_gettext(message: str) -> str:
    with translation.override(get_argus_telegram_language()):
        return gettext(message)


@contextmanager
def override_argus_telegram_language(language: str):
    token = _telegram_language.set(language)
    try:
        with translation.override(language):
            yield
    finally:
        _telegram_language.reset(token)
