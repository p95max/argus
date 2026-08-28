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


@dataclass(frozen=True)
class ListingAnalytics:
    total_views: int
    total_delta_24h: int | None
    listings: tuple[ListingAnalyticsItem, ...]


def get_listing_analytics(*, now=None) -> ListingAnalytics | None:
    """Read saved view counters only; this function never contacts Kleinanzeigen."""

    now = now or timezone.now()
    cutoff = now - timedelta(hours=24)
    items = []
    for listing in (
        Listing.objects.exclude(kleinanzeigen_url="")
        .filter(views_count__isnull=False)
        .prefetch_related("view_stats")
    ):
        baseline = next(
            (
                snapshot
                for snapshot in listing.view_stats.all()
                if snapshot.created_at <= cutoff
            ),
            None,
        )
        delta = listing.views_count - baseline.views_count if baseline else None
        items.append(
            ListingAnalyticsItem(
                listing_id=listing.id,
                title=listing.title,
                views_count=listing.views_count,
                views_delta_24h=delta,
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
    known_deltas = [item.views_delta_24h for item in items if item.views_delta_24h is not None]
    return ListingAnalytics(
        total_views=sum(item.views_count for item in items),
        total_delta_24h=sum(known_deltas) if known_deltas else None,
        listings=tuple(items),
    )
