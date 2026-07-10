from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import MarketplaceAlert


def _safe_next_url(request):
    fallback = reverse("mobile_dashboard") + "?view=archived"
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
def mobile_clear_archived_alerts(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied("Only staff users can clear archived leads.")

    archived_alerts = MarketplaceAlert.objects.filter(
        alert_status=MarketplaceAlert.AlertStatus.ARCHIVED
    )

    if not archived_alerts.exists():
        messages.info(request, _("The lead archive is already empty."))
        return redirect(_safe_next_url(request))

    archived_count = archived_alerts.count()
    archived_alerts.delete()
    messages.success(
        request,
        _("Lead archive cleared. Deleted records: %(count)s.")
        % {"count": archived_count},
    )
    return redirect(_safe_next_url(request))
