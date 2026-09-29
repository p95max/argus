from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

from ...models import Listing, ListingViewStat, MarketplaceAlert
from ...services.listing_analytics import get_listing_analytics


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


def _growth_events_by_listing():
    """Load saved view growth once and group it by listing."""
    events_by_listing = {}
    previous_by_listing = {}
    stats = (
        ListingViewStat.objects.select_related("listing")
        .filter(
            listing__kleinanzeigen_url__gt="",
            listing__is_active=True,
            listing__kleinanzeigen_status=Listing.KleinanzeigenStatus.ACTIVE,
        )
        .order_by("listing_id", "created_at", "id")
    )

    for stat in stats:
        previous = previous_by_listing.get(stat.listing_id)
        if previous is not None:
            delta = max(stat.views_count - previous, 0)
            if delta:
                events_by_listing.setdefault(stat.listing_id, []).append(
                    (stat.created_at, delta)
                )
        previous_by_listing[stat.listing_id] = stat.views_count

    return events_by_listing


def _build_all_listings_history(analytics):
    """Build per-day view gains from consecutive snapshots.

    The first snapshot is a baseline, not views gained on its calendar day.
    Deltas are attributed to the day of the later snapshot. A date is shown
    only once at least one real delta exists for it.
    """
    if not analytics or not analytics.listings:
        return {"labels": [], "series": []}

    listing_titles = {item.listing_id: item.title for item in analytics.listings}
    daily_gains = {listing_id: {} for listing_id in listing_titles}
    days = set()

    stats = (
        ListingViewStat.objects.filter(listing_id__in=listing_titles)
        .order_by("listing_id", "created_at", "id")
        .values("listing_id", "views_count", "created_at")
    )

    previous_by_listing = {}
    for stat in stats:
        listing_id = stat["listing_id"]
        previous = previous_by_listing.get(listing_id)
        if previous is not None:
            day = timezone.localtime(stat["created_at"]).date()
            delta = max(stat["views_count"] - previous, 0)
            daily_gains[listing_id][day] = daily_gains[listing_id].get(day, 0) + delta
            days.add(day)
        previous_by_listing[listing_id] = stat["views_count"]

    ordered_days = sorted(days)
    if not ordered_days:
        return {"labels": [], "series": []}

    series = []
    for listing_id, title in listing_titles.items():
        gains = daily_gains.get(listing_id, {})
        values = [gains.get(day) for day in ordered_days]
        if any(value is not None for value in values):
            series.append(
                {
                    "listing_id": listing_id,
                    "title": title,
                    "values": values,
                }
            )

    return {
        "labels": [day.strftime("%d.%m") for day in ordered_days],
        "series": series,
    }

def _build_hourly_chart(events, now):
    local_now = timezone.localtime(now)
    start = local_now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    buckets = [start + timedelta(hours=index) for index in range(24)]
    values = {bucket: 0 for bucket in buckets}

    for created_at, delta in events:
        local_created_at = timezone.localtime(created_at)
        bucket = local_created_at.replace(minute=0, second=0, microsecond=0)
        if bucket in values:
            values[bucket] += delta

    return [
        {"label": bucket.strftime("%H:%M"), "value": values[bucket]}
        for bucket in buckets
    ]


def _build_daily_chart(events, now):
    today = timezone.localtime(now).date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    values = {day: 0 for day in days}

    for created_at, delta in events:
        day = timezone.localtime(created_at).date()
        if day in values:
            values[day] += delta

    return [
        {"label": day.strftime("%d.%m"), "value": values[day]}
        for day in days
    ]


def _build_all_time_daily_chart(events):
    """Aggregate saved view growth by day for the full listing history."""
    if not events:
        return []

    values = {}
    for created_at, delta in events:
        day = timezone.localtime(created_at).date()
        values[day] = values.get(day, 0) + delta

    start = min(values)
    end = max(values)
    days = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)

    return [
        {"label": day.strftime("%d.%m"), "value": values.get(day, 0)}
        for day in days
    ]


def _build_all_time_hour_chart(events):
    """Aggregate all saved view growth by local hour of day."""
    values = {hour: 0 for hour in range(24)}
    for created_at, delta in events:
        hour = timezone.localtime(created_at).hour
        values[hour] += delta

    return [
        {"label": f"{hour:02d}:00", "value": values[hour]}
        for hour in range(24)
    ]


def _build_chart_set(events, now):
    return {
        "chart_24h": _build_hourly_chart(events, now),
        "chart_7d": _build_daily_chart(events, now),
        "chart_all_time": _build_all_time_daily_chart(events),
        "chart_hours_all_time": _build_all_time_hour_chart(events),
    }


def _percentage_change(current, previous):
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _inquiry_events_by_listing(now):
    """Group buyer-message events by tracked Kleinanzeigen listing."""
    listings = list(
        Listing.objects.filter(is_active=True)
        .exclude(kleinanzeigen_listing_id="")
        .only("id", "title", "kleinanzeigen_listing_id")
        .order_by("title", "id")
    )
    by_external_id = {
        listing.kleinanzeigen_listing_id: listing
        for listing in listings
    }
    events_by_listing = {listing.id: [] for listing in listings}

    alerts = (
        MarketplaceAlert.objects.filter(
            event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
            listing_id__in=by_external_id,
        )
        .values("listing_id", "received_at", "created_at")
        .order_by("received_at", "created_at", "id")
    )
    for alert in alerts:
        listing = by_external_id.get(alert["listing_id"])
        if listing is None:
            continue
        occurred_at = alert["received_at"] or alert["created_at"]
        if occurred_at > now:
            continue
        events_by_listing[listing.id].append((occurred_at, 1))

    return listings, events_by_listing


def _count_events_between(events, start, end):
    return sum(delta for created_at, delta in events if start < created_at <= end)


def _build_inquiry_chart_sets(listings, events_by_listing, now):
    cutoff_24h = now - timedelta(hours=24)
    cutoff_48h = now - timedelta(hours=48)
    cutoff_7d = now - timedelta(days=7)
    cutoff_14d = now - timedelta(days=14)

    all_events = [
        event
        for listing_events in events_by_listing.values()
        for event in listing_events
    ]

    def build(title, events):
        total = sum(delta for _, delta in events)
        current_24h = _count_events_between(events, cutoff_24h, now)
        previous_24h = _count_events_between(events, cutoff_48h, cutoff_24h)
        current_7d = _count_events_between(events, cutoff_7d, now)
        previous_7d = _count_events_between(events, cutoff_14d, cutoff_7d)
        return {
            "title": title,
            "views_count": total,
            "delta_24h": current_24h,
            "delta_7d": current_7d,
            "change_24h_pct": _percentage_change(current_24h, previous_24h),
            "change_7d_pct": _percentage_change(current_7d, previous_7d),
            **_build_chart_set(events, now),
        }

    chart_sets = {"all": build("Все объявления", all_events)}
    for listing in listings:
        chart_sets[str(listing.id)] = build(
            listing.title,
            events_by_listing.get(listing.id, []),
        )
    return chart_sets


def _build_inquiry_all_listings_history(listings, events_by_listing):
    days = set()
    daily_by_listing = {}

    for listing in listings:
        daily = {}
        for created_at, delta in events_by_listing.get(listing.id, []):
            day = timezone.localtime(created_at).date()
            daily[day] = daily.get(day, 0) + delta
            days.add(day)
        daily_by_listing[listing.id] = daily

    ordered_days = sorted(days)
    series = []
    for listing in listings:
        daily = daily_by_listing.get(listing.id, {})
        values = [daily.get(day, 0) for day in ordered_days]
        if any(values):
            series.append(
                {
                    "listing_id": listing.id,
                    "title": listing.title,
                    "values": values,
                }
            )

    return {
        "labels": [day.strftime("%d.%m") for day in ordered_days],
        "series": series,
    }


@login_required
def mobile_analytics(request):
    _require_staff(request.user)

    now = timezone.now()
    analytics = get_listing_analytics(now=now)
    events_by_listing = _growth_events_by_listing()

    all_events = [
        event
        for listing_events in events_by_listing.values()
        for event in listing_events
    ]
    chart_sets = {
        "all": {
            "title": "Все объявления",
            "views_count": analytics.total_views if analytics else 0,
            "delta_24h": analytics.total_delta_24h if analytics else None,
            "delta_7d": analytics.total_delta_7d if analytics else None,
            "change_24h_pct": analytics.total_change_24h_pct if analytics else None,
            "change_7d_pct": analytics.total_change_7d_pct if analytics else None,
            **_build_chart_set(all_events, now),
        }
    }

    if analytics:
        for item in analytics.listings:
            chart_sets[str(item.listing_id)] = {
                "title": item.title,
                "views_count": item.views_count,
                "delta_24h": item.views_delta_24h,
                "delta_7d": item.views_delta_7d,
                "change_24h_pct": None,
                "change_7d_pct": None,
                **_build_chart_set(events_by_listing.get(item.listing_id, []), now),
            }

    inquiry_listings, inquiry_events = _inquiry_events_by_listing(now)
    inquiry_chart_sets = _build_inquiry_chart_sets(
        inquiry_listings,
        inquiry_events,
        now,
    )

    listing_tabs = []
    seen_listing_ids = set()
    if analytics:
        for item in analytics.listings:
            listing_tabs.append({"listing_id": item.listing_id, "title": item.title})
            seen_listing_ids.add(item.listing_id)
    for listing in inquiry_listings:
        if listing.id not in seen_listing_ids:
            listing_tabs.append({"listing_id": listing.id, "title": listing.title})

    return render(
        request,
        "mobile/analytics.html",
        {
            "analytics": analytics,
            "listing_tabs": listing_tabs,
            "chart_sets": chart_sets,
            "all_listings_history": _build_all_listings_history(analytics),
            "inquiry_chart_sets": inquiry_chart_sets,
            "inquiry_all_listings_history": _build_inquiry_all_listings_history(
                inquiry_listings,
                inquiry_events,
            ),
        },
    )
