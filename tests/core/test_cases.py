from datetime import timedelta

import pytest
from django.utils import timezone

from alerts.cases import build_case_summaries
from alerts.models import LeadFlag, MailboxAccount, MarketplaceAlert


@pytest.mark.django_db
def test_build_case_summaries_groups_by_mailbox_and_listing():
    mailbox = MailboxAccount.objects.create(name="Inbox", email="inbox@example.local")
    other_mailbox = MailboxAccount.objects.create(name="Other", email="other@example.local")
    risk_flag = LeadFlag.objects.create(
        code="risk",
        name="Risk",
        category=LeadFlag.Category.RISK,
    )
    low_quality_flag = LeadFlag.objects.create(
        code="low-quality",
        name="Low quality",
        category=LeadFlag.Category.LOW_QUALITY,
    )
    older = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="listing-1",
        subject="Older subject",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        priority=MarketplaceAlert.Priority.LOW,
    )
    older.flags.add(low_quality_flag)
    latest = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="listing-1",
        listing_title="BMW 320d",
        buyer_name="Max",
        alert_status=MarketplaceAlert.AlertStatus.IN_WORK,
        priority=MarketplaceAlert.Priority.HIGH,
    )
    latest.flags.add(risk_flag)
    MarketplaceAlert.objects.filter(id=older.id).update(
        created_at=timezone.now() - timedelta(minutes=10),
    )
    MarketplaceAlert.objects.filter(id=latest.id).update(created_at=timezone.now())
    MarketplaceAlert.objects.create(
        mailbox=other_mailbox,
        listing_id="listing-2",
        listing_title="VW Golf",
        alert_status=MarketplaceAlert.AlertStatus.IGNORED,
    )
    MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="",
        listing_title="No listing id",
    )

    summaries = build_case_summaries()

    assert len(summaries) == 2
    summary = next(item for item in summaries if item["listing_id"] == "listing-1")
    assert summary["mailbox_id"] == mailbox.id
    assert summary["mailbox__name"] == "Inbox"
    assert summary["total"] == 2
    assert summary["unread"] == 1
    assert summary["in_work"] == 1
    assert summary["high_priority"] == 1
    assert summary["risk"] == 1
    assert summary["low_quality"] == 1
    assert summary["title"] == "BMW 320d"
    assert summary["last_buyer"] == "Max"
    assert summary["latest_alert_id"] == latest.id
    assert summary["case_status"] == "active"

    inactive_summary = next(item for item in summaries if item["listing_id"] == "listing-2")
    assert inactive_summary["case_status"] == "inactive"
