from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from .models import MarketplaceAlert


@login_required
def mobile_listings(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")

    alerts = (
        MarketplaceAlert.objects.filter(event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
        .select_related("mailbox", "taken_by")
        .prefetch_related("flags")
        .order_by("-received_at", "-created_at", "-id")
    )

    grouped = OrderedDict()
    for alert in alerts:
        key = (
            alert.mailbox_id,
            alert.listing_id or alert.listing_title or alert.subject or f"alert-{alert.id}",
        )
        group = grouped.setdefault(
            key,
            {
                "title": alert.listing_title or alert.subject or alert.get_event_type_display(),
                "listing_id": alert.listing_id,
                "alerts": [],
                "open_count": 0,
                "processed_count": 0,
            },
        )
        group["alerts"].append(alert)
        if alert.alert_status == MarketplaceAlert.AlertStatus.ARCHIVED:
            group["processed_count"] += 1
        elif alert.alert_status != MarketplaceAlert.AlertStatus.IGNORED:
            group["open_count"] += 1

    listing_groups = list(grouped.values())
    return render(
        request,
        "mobile/listings.html",
        {
            "listing_groups": listing_groups,
            "listing_count": len(listing_groups),
            "alert_count": sum(len(group["alerts"]) for group in listing_groups),
        },
    )
