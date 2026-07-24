from django.contrib import admin
from django.utils.translation import gettext_lazy as _


ADMIN_SECTIONS = (
    ("argus_mail", _("Mail"), {"MailboxAccount", "ProcessedEmail"}),
    (
        "argus_leads",
        _("Leads"),
        {"MarketplaceAlert", "NoiseAlert", "LeadFlag"},
    ),
    ("argus_settings", _("Settings"), {"ArgusSettings", "TelegramSettings"}),
    ("argus_system", _("System"), {"ServiceEvent", "AdminLoginLog"}),
)


def configure_admin_navigation():
    if getattr(admin.site, "_argus_navigation_configured", False):
        return

    original_get_app_list = admin.site.get_app_list

    def get_app_list(request, app_label=None):
        app_list = original_get_app_list(request, app_label)
        if app_label is not None:
            return app_list

        alerts_app = next(
            (app for app in app_list if app["app_label"] == "alerts"),
            None,
        )
        if not alerts_app:
            return app_list

        models_by_name = {
            model["object_name"]: model for model in alerts_app["models"]
        }
        sectioned_models = {
            model_name
            for _, _, model_names in ADMIN_SECTIONS
            for model_name in model_names
        }
        alerts_app["models"] = [
            model
            for model in alerts_app["models"]
            if model["object_name"] not in sectioned_models
        ]
        if not alerts_app["models"]:
            app_list.remove(alerts_app)

        sections = []
        for section_label, section_name, model_names in ADMIN_SECTIONS:
            models = [
                models_by_name[model_name]
                for model_name in model_names
                if model_name in models_by_name
            ]
            if models:
                sections.append(
                    {
                        "name": section_name,
                        "app_label": section_label,
                        "app_url": "",
                        "has_module_perms": True,
                        "models": models,
                    }
                )

        auth_index = next(
            (index for index, app in enumerate(app_list) if app["app_label"] == "auth"),
            -1,
        )
        insert_at = auth_index + 1 if auth_index >= 0 else len(app_list)
        app_list[insert_at:insert_at] = sections
        return app_list

    admin.site.get_app_list = get_app_list
    admin.site._argus_navigation_configured = True
