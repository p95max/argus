from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count, F, Max, Q, QuerySet
from django.utils import timezone

from .models import MarketplaceAlert


DEFAULT_CLEANUP_OLD_LEADS_DAYS = 30
ACTIVE_ALERT_STATUSES = (
    MarketplaceAlert.AlertStatus.UNREAD,
    MarketplaceAlert.AlertStatus.IN_WORK,
)
INACTIVE_ALERT_STATUSES = (MarketplaceAlert.AlertStatus.IGNORED,)


@dataclass(frozen=True)
class CaseCleanupResult:
    selected_cases: int = 0
    deleted_alerts: int = 0


def close_cases_for_alerts(alerts: QuerySet[MarketplaceAlert]) -> CaseCleanupResult:
    case_keys = _case_keys(alerts)
    if not case_keys:
        return CaseCleanupResult()
    return _delete_case_keys(case_keys)


def cleanup_old_leads(
    *,
    older_than_days: int = DEFAULT_CLEANUP_OLD_LEADS_DAYS,
    limit: int | None = None,
    dry_run: bool = False,
) -> CaseCleanupResult:
    cutoff = timezone.now() - timezone.timedelta(days=older_than_days)
    branches = (
        MarketplaceAlert.objects.exclude(listing_id="")
        .values("mailbox_id", "listing_id")
        .annotate(
            total=Count("id"),
            active_count=Count("id", filter=Q(alert_status__in=ACTIVE_ALERT_STATUSES)),
            inactive_count=Count("id", filter=Q(alert_status__in=INACTIVE_ALERT_STATUSES)),
            newest_updated_at=Max("updated_at"),
        )
        .filter(
            active_count=0,
            inactive_count__gt=0,
            total=F("inactive_count"),
            newest_updated_at__lt=cutoff,
        )
        .order_by("newest_updated_at", "mailbox_id", "listing_id")
    )
    if limit is not None:
        branches = branches[:limit]

    case_keys = [(branch["mailbox_id"], branch["listing_id"]) for branch in branches]
    if dry_run or not case_keys:
        return CaseCleanupResult(selected_cases=len(case_keys), deleted_alerts=0)
    return _delete_case_keys(case_keys)


def _case_keys(alerts: QuerySet[MarketplaceAlert]) -> list[tuple[int, str]]:
    return list(
        alerts.exclude(listing_id="")
        .values_list("mailbox_id", "listing_id")
        .distinct()
    )


@transaction.atomic
def _delete_case_keys(case_keys: list[tuple[int, str]]) -> CaseCleanupResult:
    case_filter = Q()
    for mailbox_id, listing_id in case_keys:
        case_filter |= Q(mailbox_id=mailbox_id, listing_id=listing_id)

    alerts = MarketplaceAlert.objects.filter(case_filter)
    deleted_alerts = alerts.count()
    alerts.delete()
    return CaseCleanupResult(selected_cases=len(case_keys), deleted_alerts=deleted_alerts)
