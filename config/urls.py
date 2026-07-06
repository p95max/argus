from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.generic import RedirectView

from django.conf import settings
from alerts import mobile


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health_check, name="health"),
    path(
        "favicon.ico",
        RedirectView.as_view(url=f"/{settings.STATIC_URL}favicon.svg", permanent=True),
        name="favicon",
    ),
    path("m/", mobile.mobile_dashboard, name="mobile_dashboard"),
    path("m/alerts/<int:alert_id>/", mobile.mobile_alert_detail, name="mobile_alert_detail"),
    path(
        "m/alerts/<int:alert_id>/status/",
        mobile.mobile_update_alert_status,
        name="mobile_update_alert_status",
    ),
    path(
        "m/telegram/quiet-hours/toggle/",
        mobile.mobile_toggle_quiet_hours,
        name="mobile_toggle_quiet_hours",
    ),
    path(
        "m/mailboxes/<int:mailbox_id>/check-now/",
        mobile.mobile_check_mailbox_now,
        name="mobile_check_mailbox_now",
    ),
    path(f"{settings.DJANGO_ADMIN_URL}/", admin.site.urls),
]
