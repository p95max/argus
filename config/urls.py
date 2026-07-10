import hmac

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.generic import RedirectView

from django.conf import settings
from alerts import mobile
from alerts.health import build_health_report


def health_check(request):
    return JsonResponse({"status": "ok"})


def full_health_check(request):
    token = getattr(settings, "ARGUS_HEALTH_TOKEN", "")
    auth_header = request.headers.get("Authorization", "")
    
    has_token_access = bool(token) and hmac.compare_digest(auth_header, "Bearer " + token)
    has_staff_access = request.user.is_authenticated and request.user.is_staff

    if not has_token_access and not has_staff_access:
        return JsonResponse({"detail": "Forbidden"}, status=403)

    report = build_health_report()
    return JsonResponse(report, status=200 if report["ok"] else 503)


urlpatterns = [
    path("health/", health_check, name="health"),
    path("health/full/", full_health_check, name="health_full"),
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
        "m/service-events/<int:event_id>/action/",
        mobile.mobile_service_event_action,
        name="mobile_service_event_action",
    ),
    path(
        "m/service-events/clear/",
        mobile.mobile_clear_service_events,
        name="mobile_clear_service_events",
    ),
    path(
        "m/gmail/check-now/",
        mobile.mobile_check_gmail_now,
        name="mobile_check_gmail_now",
    ),
    path(
        "m/mailboxes/<int:mailbox_id>/check-now/",
        mobile.mobile_check_mailbox_now,
        name="mobile_check_mailbox_now",
    ),
    path(f"{settings.DJANGO_ADMIN_URL}/", admin.site.urls),
]
