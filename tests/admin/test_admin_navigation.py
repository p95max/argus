from django.contrib import admin
from django.test import RequestFactory

from alerts.admin_site.navigation import ADMIN_SECTIONS, configure_admin_navigation


def test_admin_navigation_splits_alerts_into_sections(monkeypatch):
    alerts_app = {
        "name": "Mail and leads",
        "app_label": "alerts",
        "app_url": "/control/alerts/",
        "has_module_perms": True,
        "models": [
            {"object_name": model_name, "name": model_name}
            for _, _, model_names in ADMIN_SECTIONS
            for model_name in model_names
        ]
        + [{"object_name": "AdminLoginLog", "name": "Access logs"}],
    }
    auth_app = {
        "name": "Authentication and Authorization",
        "app_label": "auth",
        "app_url": "/control/auth/",
        "has_module_perms": True,
        "models": [],
    }

    monkeypatch.setattr(
        admin.site,
        "get_app_list",
        lambda request, app_label=None: [auth_app, alerts_app],
    )
    monkeypatch.delattr(admin.site, "_argus_navigation_configured", raising=False)
    configure_admin_navigation()

    app_list = admin.site.get_app_list(RequestFactory().get("/control/"))

    assert [app["app_label"] for app in app_list] == [
        "auth",
        "argus_mail",
        "argus_leads",
        "argus_settings",
        "argus_system",
    ]
