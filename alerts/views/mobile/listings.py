from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ...services.kleinanzeigen import (
    KleinanzeigenURLValidationError,
    ListingViewCheck,
    validate_kleinanzeigen_url,
    verify_listing_url,
)
from ...services.listing_analytics import get_listing_analytics
from ...models import Listing, ListingViewStat, MarketplaceAlert


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
    trackers_by_alert_id = {
        listing.source_alert_id: listing
        for listing in Listing.objects.select_related("mailbox").exclude(source_alert__isnull=True)
    }
    for group in listing_groups:
        group["statistics"] = next(
            (
                trackers_by_alert_id[alert.id]
                for alert in group["alerts"]
                if alert.id in trackers_by_alert_id
            ),
            None,
        )

    analytics = get_listing_analytics()
    deltas = {
        item.listing_id: item.views_delta_24h
        for item in (analytics.listings if analytics else ())
    }
    for listing in trackers_by_alert_id.values():
        listing.views_delta_24h = deltas.get(listing.id)

    return render(
        request,
        "mobile/listings.html",
        {
            "listing_groups": listing_groups,
            "listing_count": len(listing_groups),
            "alert_count": sum(len(group["alerts"]) for group in listing_groups),
        },
    )


def _save_listing_from_request(
    request,
    listing: Listing,
    *,
    title: str | None = None,
    mailbox=None,
    is_active: bool | None = None,
) -> ListingViewCheck | None:
    title = (title if title is not None else request.POST.get("title") or "").strip()
    if not title:
        raise ValueError("title_required")

    listing.title = title
    if mailbox is not None:
        listing.mailbox = mailbox
    listing.is_active = request.POST.get("is_active") == "on" if is_active is None else is_active
    raw_url = (request.POST.get("kleinanzeigen_url") or "").strip()
    if not raw_url:
        listing.kleinanzeigen_url = ""
        listing.kleinanzeigen_listing_id = ""
        listing.views_count = None
        listing.views_checked_at = None
        listing.views_error = ""
        listing.save()
        return None

    validated = validate_kleinanzeigen_url(raw_url)
    url_changed = listing.kleinanzeigen_url != validated.normalized_url
    listing.kleinanzeigen_url = validated.normalized_url
    listing.kleinanzeigen_listing_id = validated.listing_id
    if url_changed:
        listing.views_count = None
        listing.views_checked_at = None
        listing.views_error = ""
    listing.save()

    try:
        result = verify_listing_url(validated.normalized_url)
    except Exception:
        result = ListingViewCheck(None, "listing_unavailable")
    if result.verified:
        changed = listing.views_count != result.views_count
        listing.views_count = result.views_count
        listing.views_checked_at = timezone.now()
        listing.views_error = ""
        listing.save(update_fields=["views_count", "views_checked_at", "views_error", "updated_at"])
        if changed:
            ListingViewStat.objects.create(listing=listing, views_count=result.views_count)
    else:
        listing.views_error = result.error
        listing.save(update_fields=["views_error", "updated_at"])
    return result


@login_required
@require_GET
def mobile_validate_kleinanzeigen_url(request):
    _require_staff(request.user)
    raw_url = request.GET.get("url", "")
    try:
        validated = validate_kleinanzeigen_url(raw_url)
    except KleinanzeigenURLValidationError:
        return JsonResponse({"valid": False, "error": "invalid_listing_url"})

    try:
        result = verify_listing_url(validated.normalized_url)
    except Exception:
        result = ListingViewCheck(None, "listing_unavailable")
    payload = {
        "valid": True,
        "listing_id": validated.listing_id,
        "status": "verified" if result.verified else "valid_unverified",
    }
    if result.verified:
        payload["views"] = result.views_count
    else:
        payload["error"] = result.error
    return JsonResponse(payload)


@login_required
@require_POST
def mobile_create_listing(request):
    _require_staff(request.user)
    listing = Listing()
    try:
        result = _save_listing_from_request(request, listing)
    except (KleinanzeigenURLValidationError, ValueError):
        messages.error(request, "Укажите название и корректную ссылку Kleinanzeigen.")
        return redirect("mobile_listings")

    if result is not None and not result.verified:
        messages.warning(request, "Ссылка сохранена, но статистика пока недоступна.")
    else:
        messages.success(request, "Объявление сохранено.")
    return redirect("mobile_listings")


@login_required
@require_POST
def mobile_configure_listing_statistics(request, alert_id):
    """Save a Kleinanzeigen URL directly on the selected marketplace listing card."""
    _require_staff(request.user)

    alert = get_object_or_404(
        MarketplaceAlert.objects.select_related("mailbox"),
        id=alert_id,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )
    listing, _ = Listing.objects.get_or_create(
        source_alert=alert,
        defaults={
            "title": alert.listing_title or alert.subject or str(alert.id),
            "mailbox": alert.mailbox,
            "is_active": True,
        },
    )
    try:
        result = _save_listing_from_request(
            request,
            listing,
            title=alert.listing_title or alert.subject or str(alert.id),
            mailbox=alert.mailbox,
            is_active=True,
        )
    except KleinanzeigenURLValidationError:
        messages.error(request, "Укажите корректную ссылку Kleinanzeigen.")
    else:
        if result is not None and not result.verified:
            messages.warning(request, "Ссылка сохранена, но статистика пока недоступна.")
        else:
            messages.success(request, "Ссылка Kleinanzeigen привязана к объявлению.")
    return redirect("mobile_listings")


@login_required
def mobile_edit_listing(request, listing_id):
    _require_staff(request.user)
    listing = get_object_or_404(Listing, id=listing_id)
    if request.method == "POST":
        try:
            result = _save_listing_from_request(request, listing)
        except (KleinanzeigenURLValidationError, ValueError):
            messages.error(request, "Укажите название и корректную ссылку Kleinanzeigen.")
        else:
            if result is not None and not result.verified:
                messages.warning(request, "Ссылка сохранена, но статистика пока недоступна.")
            else:
                messages.success(request, "Объявление сохранено.")
            return redirect("mobile_edit_listing", listing_id=listing.id)
    return render(request, "mobile/listing_edit.html", {"listing": listing})


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
