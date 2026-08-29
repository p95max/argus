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


def _delta_since(listing, cutoff):
    baseline = next(
        (
            snapshot
            for snapshot in listing.view_stats.all()
            if snapshot.created_at <= cutoff
        ),
        None,
    )
    return listing.views_count - baseline.views_count if baseline else None


def get_listing_analytics(*, now=None) -> ListingAnalytics | None:
    """Read saved view counters only; this function never contacts Kleinanzeigen."""

    now = now or timezone.now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    items = []
    for listing in (
        Listing.objects.exclude(kleinanzeigen_url="")
        .filter(views_count__isnull=False)
        .prefetch_related("view_stats")
    ):
        delta_24h = _delta_since(listing, cutoff_24h)
        delta_7d = _delta_since(listing, cutoff_7d)
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
    return ListingAnalytics(
        total_views=sum(item.views_count for item in items),
        total_delta_24h=sum(known_24h) if known_24h else None,
        total_delta_7d=sum(known_7d) if known_7d else None,
        listings=tuple(items),
    )
