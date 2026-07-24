import ipaddress

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.utils import timezone

from .models import AdminLoginLog
from .security import _client_ip


@receiver(user_logged_in, dispatch_uid="alerts.log_admin_login")
def log_admin_login(sender, request, user, **kwargs):
    if request.path != f"/{settings.DJANGO_ADMIN_URL}/login/" or not user.is_staff:
        return

    ip_address = _client_ip(request)
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        ip_address = None

    entry = AdminLoginLog.objects.create(
        user=user,
        ip_address=ip_address,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        path=request.path[:500],
        session_key=request.session.session_key or "",
    )
    request.session["admin_login_log_id"] = entry.pk


@receiver(user_logged_out, dispatch_uid="alerts.log_admin_logout")
def log_admin_logout(sender, request, user, **kwargs):
    entry_id = request.session.get("admin_login_log_id")
    if entry_id:
        AdminLoginLog.objects.filter(pk=entry_id, logged_out_at__isnull=True).update(
            logged_out_at=timezone.now()
        )
