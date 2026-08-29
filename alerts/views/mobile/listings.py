from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ...services.kleinanzeigen import (
    canonicalize_kleinanzeigen_ad_id,
    KleinanzeigenURLValidationError,
    ListingViewCheck,
    VIEW_COUNTER_REFRESH_INTERVAL,
    validate_kleinanzeigen_url,
    verify_listing_url,
)
from ...services.listing_analytics import get_listing_analytics
from ...services.listing_metadata import fetch_listing_public_metadata
from ...models import Listing, ListingViewStat, MarketplaceAlert


LISTING_CLOSED_MARKER = "__listing_closed__"


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


def _same_listing_queryset(alert):
    queryset = MarketplaceAlert.objects.filter(event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)

    if alert.listing_id:
        return queryset.filter(listing_id=alert.listing_id)
    queryset = queryset.filter(mailbox_id=alert.mailbox_id)
    if alert.listing_title:
        return queryset.filter(listing_title=alert.listing_title)
    if alert.subject:
        return queryset.filter(subject=alert.subject)
    return queryset.filter(id=alert.id)


def _normalize_listing_title(value):
    """Normalize a listing title for conservative fallback grouping."""
    return " ".join((value or "").split()).casefold()


def _canonical_alert_listing_id(alert):
    return canonicalize_kleinanzeigen_ad_id(alert.listing_id) or alert.listing_id


def _build_listing_group_keys(alerts):
    """Map title-only alerts to a listing ID only when that title identifies one listing."""
    title_listing_ids = {}
    for alert in alerts:
        if not alert.listing_id:
            continue
        title = _normalize_listing_title(alert.listing_title or alert.subject)
        if title:
            title_listing_ids.setdefault(title, set()).add(_canonical_alert_listing_id(alert))

    keys = {}
    for alert in alerts:
        if alert.listing_id:
            keys[alert.id] = (f"id:{_canonical_alert_listing_id(alert)}",)
            continue

        title_value = alert.listing_title or alert.subject
        title = _normalize_listing_title(title_value)
        matching_ids = title_listing_ids.get(title, set())
        if title and len(matching_ids) == 1:
            listing_id = next(iter(matching_ids))
            keys[alert.id] = (f"id:{listing_id}",)
        elif title:
            keys[alert.id] = (alert.mailbox_id, f"title:{title}")
        else:
            keys[alert.id] = (alert.mailbox_id, f"alert:{alert.id}")
    return keys


def _publication_icon(age_days):
    if age_days <= 7:
        return "🟢"
    if age_days < 14:
        return "🟡"
    return "🔴"


def _days_label(days):
    days = max(int(days), 0)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days % 10 == 1 and days % 100 != 11:
        word = "день"
    elif days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word} назад"


def _attach_mobile_listing_analytics(listing, *, today):
    listing.publication_date = None
    listing.publication_age_days = None
    listing.publication_age_label = ""
    listing.publication_icon = "⚪"
    listing.last_activity_date = None
    listing.last_activity_age_days = None
    listing.last_activity_age_label = ""
    listing.last_activity_stale = False

    if listing.kleinanzeigen_url:
        try:
            metadata = fetch_listing_public_metadata(listing.kleinanzeigen_url)
        except Exception:
            metadata = None
        if metadata and metadata.published_on:
            listing.publication_date = metadata.published_on
            listing.publication_age_days = max((today - metadata.published_on).days, 0)
            listing.publication_age_label = _days_label(listing.publication_age_days)
            listing.publication_icon = _publication_icon(listing.publication_age_days)

    latest_stat = next(iter(listing.view_stats.all()), None)
    if latest_stat is not None:
        activity_date = timezone.localtime(latest_stat.created_at).date()
        listing.last_activity_date = activity_date
        listing.last_activity_age_days = max((today - activity_date).days, 0)
        listing.last_activity_age_label = _days_label(listing.last_activity_age_days)
        listing.last_activity_stale = listing.last_activity_age_days > 7


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
                "listing_id": _canonical_alert_listing_id(alert),
                "alerts": [],
                "open_count": 0,
                "processed_count": 0,
                "representative_alert_id": alert.id,
                "is_closed": False,
            },
        )
        if not group["listing_id"] and alert.listing_id:
            group["listing_id"] = _canonical_alert_listing_id(alert)
        group["alerts"].append(alert)
        if alert.taken_by_label == LISTING_CLOSED_MARKER:
            group["is_closed"] = True
        if alert.alert_status == MarketplaceAlert.AlertStatus.ARCHIVED:
            group["processed_count"] += 1
        elif alert.alert_status != MarketplaceAlert.AlertStatus.IGNORED:
            group["open_count"] += 1

    listing_groups = list(grouped.values())
    trackers_by_listing_id = {
        listing.kleinanzeigen_listing_id: listing
        for listing in Listing.objects.select_related("mailbox")
        .prefetch_related("view_stats")
        .exclude(kleinanzeigen_listing_id="")
    }
    for group in listing_groups:
        group["statistics"] = trackers_by_listing_id.get(group["listing_id"])

    analytics = get_listing_analytics()
    analytics_by_id = {
        item.listing_id: item
        for item in (analytics.listings if analytics else ())
    }
    today = timezone.localdate()
    for listing in trackers_by_listing_id.values():
        item = analytics_by_id.get(listing.id)
        listing.views_delta_24h = item.views_delta_24h if item else None
        listing.views_delta_7d = item.views_delta_7d if item else None
        _attach_mobile_listing_analytics(listing, today=today)

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
    validated=None,
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

    validated = validated or validate_kleinanzeigen_url(raw_url)
    url_changed = listing.kleinanzeigen_url != validated.normalized_url
    listing.kleinanzeigen_url = validated.normalized_url
    listing.kleinanzeigen_listing_id = validated.ad_id
    if url_changed:
        listing.views_count = None
        listing.views_checked_at = None
        listing.views_error = ""
    listing.save()

    if (
        not url_changed
        and listing.views_checked_at
        and listing.views_checked_at >= timezone.now() - VIEW_COUNTER_REFRESH_INTERVAL
    ):
        return ListingViewCheck(listing.views_count, listing.views_error)

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
        listing.views_checked_at = timezone.now()
        listing.save(update_fields=["views_error", "views_checked_at", "updated_at"])
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

    return JsonResponse({
        "valid": True,
        "listing_id": validated.listing_id,
        "status": "valid",
    })


@login_required
@require_POST
def mobile_create_listing(request):
    _require_staff(request.user)
    try:
        title = (request.POST.get("title") or "").strip()
        if not title:
            raise ValueError("title_required")
        raw_url = (request.POST.get("kleinanzeigen_url") or "").strip()
        validated = validate_kleinanzeigen_url(raw_url) if raw_url else None
        listing, _ = (
            Listing.objects.get_or_create(
                kleinanzeigen_listing_id=validated.ad_id,
                defaults={
                    "title": title,
                    "kleinanzeigen_url": validated.normalized_url,
                    "is_active": request.POST.get("is_active") == "on",
                },
            )
            if validated
            else (Listing(), True)
        )
        result = _save_listing_from_request(request, listing, validated=validated)
    except (IntegrityError, KleinanzeigenURLValidationError, ValueError):
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
    try:
        raw_url = (request.POST.get("kleinanzeigen_url") or "").strip()
        validated = validate_kleinanzeigen_url(raw_url) if raw_url else None
        alert_ad_id = _canonical_alert_listing_id(alert)
        if validated and alert_ad_id.isdecimal() and alert_ad_id != validated.ad_id:
            raise ValueError("listing_id_mismatch")
        if validated:
            listing, created = Listing.objects.get_or_create(
                kleinanzeigen_listing_id=validated.ad_id,
                defaults={
                    "title": alert.listing_title or alert.subject or str(alert.id),
                    "mailbox": alert.mailbox,
                    "kleinanzeigen_url": validated.normalized_url,
                    "source_alert": alert,
                    "is_active": True,
                },
            )
        else:
            listing = Listing.objects.filter(kleinanzeigen_listing_id=alert_ad_id).first()
            if listing is None:
                listing, created = Listing.objects.get_or_create(
                    source_alert=alert,
                    defaults={
                        "title": alert.listing_title or alert.subject or str(alert.id),
                        "mailbox": alert.mailbox,
                        "is_active": True,
                    },
                )
        if not listing.source_alert_id and not Listing.objects.filter(source_alert=alert).exclude(
            pk=listing.pk
        ).exists():
            listing.source_alert = alert
        result = _save_listing_from_request(
            request,
            listing,
            title=alert.listing_title or alert.subject or str(alert.id),
            mailbox=alert.mailbox,
            is_active=True,
            validated=validated,
        )
    except (IntegrityError, KleinanzeigenURLValidationError, ValueError):
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
        except (IntegrityError, KleinanzeigenURLValidationError, ValueError):
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
