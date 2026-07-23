from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import translation
from django.utils.translation import gettext

import pytest

from alerts.admin_site.system import ArgusSettingsAdmin
from alerts.middleware import AdminSelectedLocaleMiddleware
from alerts.models import ArgusSettings, LanguageCode


@pytest.mark.django_db
def test_argus_settings_defaults_to_english_and_is_singleton():
    settings = ArgusSettings.load()
    same_settings = ArgusSettings.load()

    assert settings.language_code == LanguageCode.ENGLISH
    assert same_settings.id == settings.id
    assert ArgusSettings.objects.count() == 1


@pytest.mark.django_db
def test_locale_middleware_activates_admin_selected_language():
    ArgusSettings.objects.create(language_code=LanguageCode.GERMAN)
    request = RequestFactory().get("/")
    seen = {}

    def get_response(request):
        seen["request_language"] = request.LANGUAGE_CODE
        seen["active_language"] = translation.get_language()
        return HttpResponse("ok")

    response = AdminSelectedLocaleMiddleware(get_response)(request)

    assert seen == {
        "request_language": LanguageCode.GERMAN,
        "active_language": LanguageCode.GERMAN,
    }
    assert response.headers["Content-Language"] == LanguageCode.GERMAN


def test_argus_locale_catalogs_translate_core_labels():
    with translation.override(LanguageCode.GERMAN):
        assert gettext("Argus settings") == "Argus Einstellungen"
        assert gettext("Mobile version") == "Mobile Version"

    with translation.override(LanguageCode.RUSSIAN):
        assert gettext("Argus settings") == "Настройки Argus"
        assert gettext("Mobile version") == "Мобильная версия"


@pytest.mark.django_db
def test_argus_settings_admin_is_superuser_only():
    user_model = get_user_model()
    staff = user_model.objects.create_user(
        username="staff",
        password="pass",
        is_staff=True,
    )
    superuser = user_model.objects.create_superuser(
        username="root",
        email="root@example.local",
        password="pass",
    )
    model_admin = ArgusSettingsAdmin(ArgusSettings, admin.site)
    request = RequestFactory().get("/control/alerts/argussettings/")

    request.user = staff
    assert model_admin.has_module_permission(request) is False
    assert model_admin.has_view_permission(request) is False
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False

    request.user = superuser
    assert model_admin.has_module_permission(request) is True
    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is True
    assert model_admin.has_change_permission(request) is True


@pytest.mark.django_db
def test_argus_settings_admin_refreshes_telegram_menu_after_language_change(monkeypatch):
    settings = ArgusSettings.load()
    settings.language_code = LanguageCode.RUSSIAN
    model_admin = ArgusSettingsAdmin(ArgusSettings, admin.site)
    request = RequestFactory().post("/control/alerts/argussettings/1/change/")
    notices = []

    monkeypatch.setattr(
        "alerts.admin_site.system.refresh_telegram_command_menu",
        lambda language: language == LanguageCode.RUSSIAN,
    )
    monkeypatch.setattr(
        model_admin,
        "message_user",
        lambda request, message, level=None: notices.append((str(message), level)),
    )

    model_admin.save_model(request, settings, form=None, change=True)

    assert settings.language_code == LanguageCode.RUSSIAN
    assert notices == [("Telegram command menu updated.", None)]
