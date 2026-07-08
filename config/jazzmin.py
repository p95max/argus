HEALTH_CHECK_URL = "/health/full/"
MOBILE_DASHBOARD_URL = "/m/"


JAZZMIN_SETTINGS = {
    "site_title": "Argus",
    "site_header": "Argus",
    "site_brand": "Argus",
    "welcome_sign": "Панель управления Argus",
    "copyright": "Argus",
    "search_model": ["auth.User", "auth.Group"],
    "topmenu_links": [
        {
            "name": "Обзор",
            "url": "admin:index",
            "permissions": ["auth.view_user"],
        },
        {
            "model": "auth.User",
        },
    ],
    "usermenu_links": [
        {
            "name": "Мобильная версия",
            "url": MOBILE_DASHBOARD_URL,
        },
        {
            "name": "Состояние сервиса",
            "url": HEALTH_CHECK_URL,
        },
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],
    "order_with_respect_to": ["alerts", "auth"],
    "custom_links": {
        "Быстрый доступ": [
            {
                "name": "Мобильная версия",
                "url": MOBILE_DASHBOARD_URL,
                "icon": "fas fa-mobile-alt",
            },
        ],
    },
    "icons": {
        "alerts": "fas fa-inbox",
        "alerts.mailboxaccount": "fas fa-envelope-open-text",
        "alerts.marketplacealert": "fas fa-bell",
        "alerts.noisealert": "fas fa-volume-mute",
        "alerts.leadflag": "fas fa-flag",
        "alerts.processedemail": "fas fa-check-double",
        "alerts.serviceevent": "fas fa-heartbeat",
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
