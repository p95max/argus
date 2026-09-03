from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

from ...models import ListingViewStat
from ...services.listing_analytics import get_listing_analytics


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


def _growth_events():
    """Return timestamped positive view deltas from saved listing snapshots."""
    events = []
    previous_by_listing = {}
    stats = (
        ListingViewStat.objects.select_related("listing")
        .filter(listing__kleinanzeigen_url__gt="")
        .order_by("listing_id", "created_at", "id")
    )
    for stat in stats:
        previous = previous_by_listing.get(stat.listing_id)
        if previous is not None:
            delta = max(stat.views_count - previous, 0)
            if delta:
                events.append((stat.created_at, delta))
        previous_by_listing[stat.listing_id] = stat.views_count
    return events


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


@login_required
def mobile_analytics(request):
    _require_staff(request.user)

    now = timezone.now()
    analytics = get_listing_analytics(now=now)
    events = _growth_events()

    return render(
        request,
        "mobile/analytics.html",
        {
            "analytics": analytics,
            "chart_24h": _build_hourly_chart(events, now),
            "chart_7d": _build_daily_chart(events, now),
        },
    )
