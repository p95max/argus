from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import ServiceEvent


def _safe_next_url(request):
    fallback = reverse("mobile_dashboard")
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


@login_required
@require_POST
def mobile_clear_service_events(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied("Only a superuser can clear the system log.")

    action = request.POST.get("action", "")
    if action == "clear_resolved_service_events":
        events = ServiceEvent.objects.exclude(status=ServiceEvent.Status.OPEN)
    elif action == "clear_all_service_events":
        events = ServiceEvent.objects.all()
    else:
        raise PermissionDenied("Unknown system log cleanup action.")

    if not events.exists():
        messages.info(request, _("The system log is already empty."))
        return redirect(_safe_next_url(request))

    service_event_count = events.count()
    events.delete()
    messages.success(
        request,
        _("System log cleared. Deleted records: %(count)s.")
        % {"count": service_event_count},
    )
    return redirect(_safe_next_url(request))
