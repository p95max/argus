from django.utils.translation import gettext_lazy as _


HEALTH_CHECK_URL = "/health/full/"
MOBILE_DASHBOARD_URL = "/m/"


JAZZMIN_SETTINGS = {
    "site_title": "Argus",
    "site_header": "Argus",
    "site_brand": "Argus",
    "welcome_sign": _("Argus control panel"),
    "copyright": "Argus",
    "search_model": ["auth.User", "auth.Group"],
    "topmenu_links": [
        {
            "name": _("Overview"),
            "url": "admin:index",
            "permissions": ["auth.view_user"],
        },
        {
            "model": "auth.User",
        },
    ],
    "usermenu_links": [
        {
            "name": _("Mobile version"),
            "url": MOBILE_DASHBOARD_URL,
        },
        {
            "name": _("Service health"),
            "url": HEALTH_CHECK_URL,
        },
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": ["alerts.adminloginlog"],
    "order_with_respect_to": [
        "auth",
        "argus_mail",
        "argus_leads",
        "argus_settings",
        "argus_system",
    ],
    "custom_links": {
        "auth": [
            {
                "name": _("Access logs"),
                "url": "admin:alerts_adminloginlog_changelist",
                "icon": "fas fa-history",
                "permissions": ["alerts.view_adminloginlog"],
            },
        ],
        "Quick access": [
            {
                "name": _("Mobile version"),
                "url": MOBILE_DASHBOARD_URL,
                "icon": "fas fa-mobile-alt",
            },
        ],
    },
    "icons": {
        "alerts": "fas fa-inbox",
        "alerts.argussettings": "fas fa-language",
        "alerts.mailboxaccount": "fas fa-envelope-open-text",
        "alerts.marketplacealert": "fas fa-bell",
        "alerts.noisealert": "fas fa-volume-mute",
        "alerts.leadflag": "fas fa-flag",
        "alerts.processedemail": "fas fa-check-double",
        "alerts.serviceevent": "fas fa-heartbeat",
        "alerts.adminloginlog": "fas fa-history",
        "alerts.telegramsettings": "fas fa-paper-plane",
        "auth": "fas fa-user-shield",
        "auth.group": "fas fa-users",
        "auth.user": "fas fa-user-lock",
    },
    "default_icon_parents": "fas fa-folder",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": True,
    "custom_js": "admin/js/argus_health_modal.js",
    "changeform_format": "horizontal_tabs",
    "show_ui_builder": False,
}


JAZZMIN_UI_TWEAKS = {
    "theme": "darkly",
    "default_theme_mode": "dark",
    "navbar": "navbar-dark",
    "sidebar": "sidebar-dark-primary",
    "accent": "accent-info",
    "brand_colour": "navbar-dark",
    "navbar_fixed": True,
    "sidebar_fixed": True,
    "footer_fixed": False,
    "sidebar_nav_flat_style": True,
    "sidebar_nav_compact_style": False,
    "button_classes": {
        "primary": "btn-info",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}
