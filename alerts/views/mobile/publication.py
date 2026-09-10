from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ...models import MarketplaceAlert
from ...services.listing_publication import publication_listing_candidate, sync_listing_from_publication


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


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
def mobile_add_listing_from_publication(request, alert_id):
    _require_staff(request.user)
    alert = get_object_or_404(MarketplaceAlert.objects.select_related("mailbox"), id=alert_id)

    try:
        candidate = publication_listing_candidate(alert)
    except Exception:
        candidate = None

    if candidate is None:
        messages.info(
            request,
            "Объявление уже существует, было недавно удалено или ID/ссылка не найдены.",
        )
        return redirect(_safe_next_url(request))

    listing = sync_listing_from_publication(alert)
    if listing is None:
        messages.warning(request, "Не удалось добавить объявление из системного уведомления.")
    else:
        messages.success(request, f"Объявление добавлено: {listing.title}")

    return redirect(_safe_next_url(request))
