from __future__ import annotations

from django.db.models import Count, Max, Q

from .models import LeadFlag, MarketplaceAlert


def build_case_summaries(limit: int = 30):
    grouped = (
        MarketplaceAlert.objects.exclude(listing_id="")
        .values("mailbox_id", "mailbox__name", "mailbox__email", "listing_id")
        .annotate(
            total=Count("id"),
            unread=Count(
                "id",
                filter=Q(alert_status=MarketplaceAlert.AlertStatus.UNREAD),
            ),
            in_work=Count(
                "id",
                filter=Q(alert_status=MarketplaceAlert.AlertStatus.IN_WORK),
            ),
            high_priority=Count(
                "id",
                filter=Q(
                    priority__in=[
                        MarketplaceAlert.Priority.HIGH,
                        MarketplaceAlert.Priority.URGENT,
                    ]
                ),
            ),
            risk=Count(
                "id",
                filter=Q(flags__category=LeadFlag.Category.RISK),
                distinct=True,
            ),
            low_quality=Count(
                "id",
                filter=Q(flags__category=LeadFlag.Category.LOW_QUALITY),
                distinct=True,
            ),
            last_seen_at=Max("created_at"),
        )
        .order_by("-last_seen_at")[:limit]
    )

    summaries = []
    for item in grouped:
        latest = (
            MarketplaceAlert.objects.filter(
                mailbox_id=item["mailbox_id"],
                listing_id=item["listing_id"],
            )
            .order_by("-created_at")
            .values("id", "listing_title", "buyer_name", "subject", "alert_status")
            .first()
        )
        status = "active" if item["unread"] or item["in_work"] else "inactive"
        summaries.append(
            {
                **item,
                "title": latest["listing_title"] or latest["subject"] if latest else "",
                "last_buyer": latest["buyer_name"] if latest else "",
                "latest_alert_id": latest["id"] if latest else None,
                "case_status": status,
            }
        )
    return summaries
