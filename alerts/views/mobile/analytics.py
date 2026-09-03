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


def _growth_events_by_listing():
    """Load saved view growth once and group it by listing."""
    events_by_listing = {}
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
                events_by_listing.setdefault(stat.listing_id, []).append(
                    (stat.created_at, delta)
                )
        previous_by_listing[stat.listing_id] = stat.views_count

    return events_by_listing


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
        "chart_hours_all_time": _build_all_time_hour_chart(events),
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
                **_build_chart_set(events_by_listing.get(item.listing_id, []), now),
            }

    return render(
        request,
        "mobile/analytics.html",
        {
            "analytics": analytics,
            "chart_sets": chart_sets,
        },
    )
