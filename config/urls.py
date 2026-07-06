from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from django.conf import settings
from alerts import mobile


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('health/', health_check, name='health'),
    path("m/", mobile.mobile_dashboard, name="mobile_dashboard"),
    path("m/alerts/<int:alert_id>/status/", mobile.mobile_update_alert_status, name="mobile_update_alert_status"),
    path(f'{settings.DJANGO_ADMIN_URL}/', admin.site.urls),
]
