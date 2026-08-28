from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import MarketplaceAlert


LISTING_CLOSED_MARKER = "__listing_closed__"


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


def _same_listing_queryset(alert):
    queryset = MarketplaceAlert.objects.filter(
        mailbox_id=alert.mailbox_id,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )

    if alert.listing_id:
        return queryset.filter(listing_id=alert.listing_id)
    if alert.listing_title:
        return queryset.filter(listing_title=alert.listing_title)
    if alert.subject:
        return queryset.filter(subject=alert.subject)
    return queryset.filter(id=alert.id)


def _normalize_listing_title(value):
    """Normalize a listing title for conservative fallback grouping."""
    return " ".join((value or "").split()).casefold()


def _build_listing_group_keys(alerts):
    """Map title-only alerts to a listing ID only when that title identifies one listing."""
    title_listing_ids = {}
    for alert in alerts:
        if not alert.listing_id:
            continue
        title = _normalize_listing_title(alert.listing_title or alert.subject)
        if title:
            title_listing_ids.setdefault((alert.mailbox_id, title), set()).add(alert.listing_id)

    keys = {}
    for alert in alerts:
        if alert.listing_id:
            keys[alert.id] = (alert.mailbox_id, f"id:{alert.listing_id}")
            continue

        title_value = alert.listing_title or alert.subject
        title = _normalize_listing_title(title_value)
        matching_ids = title_listing_ids.get((alert.mailbox_id, title), set())
        if title and len(matching_ids) == 1:
            listing_id = next(iter(matching_ids))
            keys[alert.id] = (alert.mailbox_id, f"id:{listing_id}")
        elif title:
            keys[alert.id] = (alert.mailbox_id, f"title:{title}")
        else:
            keys[alert.id] = (alert.mailbox_id, f"alert:{alert.id}")
    return keys


@login_required
def mobile_listings(request):
    _require_staff(request.user)

    alerts = list(
        MarketplaceAlert.objects.filter(event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
        .select_related("mailbox", "taken_by")
        .prefetch_related("flags")
        .order_by("-received_at", "-created_at", "-id")
    )
    group_keys = _build_listing_group_keys(alerts)

    grouped = OrderedDict()
    for alert in alerts:
        key = group_keys[alert.id]
        group = grouped.setdefault(
            key,
            {
                "title": alert.listing_title or alert.subject or alert.get_event_type_display(),
                "listing_id": alert.listing_id,
                "alerts": [],
                "open_count": 0,
                "processed_count": 0,
                "representative_alert_id": alert.id,
                "is_closed": False,
            },
        )
        if not group["listing_id"] and alert.listing_id:
            group["listing_id"] = alert.listing_id
        group["alerts"].append(alert)
        if alert.taken_by_label == LISTING_CLOSED_MARKER:
            group["is_closed"] = True
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


@login_required
@require_POST
def mobile_close_listing(request, alert_id):
    _require_staff(request.user)

    alert = get_object_or_404(
        MarketplaceAlert,
        id=alert_id,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )
    same_listing = _same_listing_queryset(alert)

    same_listing.update(
        alert_status=MarketplaceAlert.AlertStatus.ARCHIVED,
        taken_by=None,
        taken_by_label="",
        taken_at=None,
    )
    same_listing.filter(id=alert.id).update(taken_by_label=LISTING_CLOSED_MARKER)

    return redirect("mobile_listings")


@login_required
@require_POST
def mobile_reopen_listing(request, alert_id):
    _require_staff(request.user)

    alert = get_object_or_404(
        MarketplaceAlert,
        id=alert_id,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )
    same_listing = _same_listing_queryset(alert)
    same_listing.filter(taken_by_label=LISTING_CLOSED_MARKER).update(taken_by_label="")

    return redirect("mobile_listings")


@login_required
@require_POST
def mobile_delete_listing(request, alert_id):
    _require_staff(request.user)

    alert = get_object_or_404(
        MarketplaceAlert,
        id=alert_id,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )
    same_listing = _same_listing_queryset(alert)

    if not same_listing.filter(taken_by_label=LISTING_CLOSED_MARKER).exists():
        raise PermissionDenied("Only closed listings can be deleted.")

    same_listing.delete()
    return redirect("mobile_listings")
