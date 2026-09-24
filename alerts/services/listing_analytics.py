"""Database-only presentation data for listing view analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from ..models import Listing


@dataclass(frozen=True)
class ListingAnalyticsItem:
    listing_id: int
    title: str
    views_count: int
    views_delta_24h: int | None
    views_delta_7d: int | None


@dataclass(frozen=True)
class ListingAnalytics:
    total_views: int
    total_delta_24h: int | None
    total_delta_7d: int | None
    listings: tuple[ListingAnalyticsItem, ...]
    total_change_24h_pct: float | None = None
    total_change_7d_pct: float | None = None


def _delta_since(listing, cutoff):
    """Return growth from the closest useful saved counter within available history."""
    snapshots = list(listing.view_stats.all())
    if not snapshots:
        return None

    older = [snapshot for snapshot in snapshots if snapshot.created_at <= cutoff]
    if older:
        baseline = max(older, key=lambda snapshot: snapshot.created_at)
    else:
        # Tracking may have started less than one full period ago. In that case
        # show growth from the first saved counter instead of hiding useful data.
        baseline = min(snapshots, key=lambda snapshot: snapshot.created_at)

    return max(listing.views_count - baseline.views_count, 0)


def _closest_snapshot(snapshots, target):
    """Return the saved counter closest to a period boundary."""
    if not snapshots:
        return None
    return min(
        snapshots,
        key=lambda snapshot: abs((snapshot.created_at - target).total_seconds()),
    )


def _period_delta(snapshots, start, end, current_views, now):
    """Return view growth between the counters closest to period boundaries."""
    start_snapshot = _closest_snapshot(snapshots, start)
    if start_snapshot is None:
        return None
    start_value = start_snapshot.views_count

    if end >= now:
        end_value = current_views
    else:
        end_snapshot = _closest_snapshot(snapshots, end)
        if end_snapshot is None or end_snapshot.created_at <= start_snapshot.created_at:
            return None
        end_value = end_snapshot.views_count

    return max(end_value - start_value, 0)


def _percentage_change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def get_listing_analytics(*, now=None) -> ListingAnalytics | None:
    """Read saved view counters only; this function never contacts Kleinanzeigen."""

    now = now or timezone.now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    items = []
    period_deltas_24h = []
    period_deltas_7d = []
    for listing in (
        Listing.objects.exclude(kleinanzeigen_url="")
        .filter(
            views_count__isnull=False,
            is_active=True,
            kleinanzeigen_status=Listing.KleinanzeigenStatus.ACTIVE,
        )
        .prefetch_related("view_stats")
    ):
        snapshots = list(listing.view_stats.all())
        delta_24h = _delta_since(listing, cutoff_24h)
        delta_7d = _delta_since(listing, cutoff_7d)

        current_24h = _period_delta(snapshots, cutoff_24h, now, listing.views_count, now)
        previous_24h = _period_delta(
            snapshots, now - timedelta(hours=48), cutoff_24h, listing.views_count, now
        )
        if current_24h is not None and previous_24h is not None:
            period_deltas_24h.append((current_24h, previous_24h))

        current_7d = _period_delta(snapshots, cutoff_7d, now, listing.views_count, now)
        previous_7d = _period_delta(
            snapshots, now - timedelta(days=14), cutoff_7d, listing.views_count, now
        )
        # A 7-day percentage is meaningful only when we have almost two full
        # weeks of saved history. Otherwise the previous "7 days" can actually
        # be a much shorter partial period and exaggerate the percentage.
        has_full_7d_comparison = bool(
            snapshots
            and min(snapshot.created_at for snapshot in snapshots)
            <= now - timedelta(days=13)
        )
        if (
            has_full_7d_comparison
            and current_7d is not None
            and previous_7d is not None
        ):
            period_deltas_7d.append((current_7d, previous_7d))

        items.append(
            ListingAnalyticsItem(
                listing_id=listing.id,
                title=listing.title,
                views_count=listing.views_count,
                views_delta_24h=delta_24h,
                views_delta_7d=delta_7d,
            )
        )

    if not items:
        return None

    items.sort(
        key=lambda item: (
            item.views_delta_24h is None,
            -(item.views_delta_24h or 0),
            item.title.casefold(),
        )
    )
    known_24h = [item.views_delta_24h for item in items if item.views_delta_24h is not None]
    known_7d = [item.views_delta_7d for item in items if item.views_delta_7d is not None]
    current_24h_total = sum(value[0] for value in period_deltas_24h)
    previous_24h_total = sum(value[1] for value in period_deltas_24h)
    current_7d_total = sum(value[0] for value in period_deltas_7d)
    previous_7d_total = sum(value[1] for value in period_deltas_7d)

    return ListingAnalytics(
        total_views=sum(item.views_count for item in items),
        total_delta_24h=sum(known_24h) if known_24h else None,
        total_delta_7d=sum(known_7d) if known_7d else None,
        listings=tuple(items),
        total_change_24h_pct=_percentage_change(
            current_24h_total, previous_24h_total
        ) if period_deltas_24h else None,
        total_change_7d_pct=_percentage_change(
            current_7d_total, previous_7d_total
        ) if period_deltas_7d else None,
    )
