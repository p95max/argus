from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import MarketplaceAlert


DEFAULT_MIN_AGE_MINUTES = 30
DEFAULT_REMINDER_INTERVAL_MINUTES = 60


def unread_alerts_due_for_reminder(
    *,
    min_age_minutes: int = DEFAULT_MIN_AGE_MINUTES,
    reminder_interval_minutes: int = DEFAULT_REMINDER_INTERVAL_MINUTES,
    now=None,
) -> QuerySet[MarketplaceAlert]:
    now = now or timezone.now()
    created_before = now - timedelta(minutes=min_age_minutes)
    reminded_before = now - timedelta(minutes=reminder_interval_minutes)

    return (
        MarketplaceAlert.objects.select_related("mailbox")
        .filter(
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
            created_at__lte=created_before,
        )
        .exclude(event_type=MarketplaceAlert.EventType.NOISE)
        .filter(Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lte=reminded_before))
        .order_by("created_at", "id")
    )
