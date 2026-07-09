from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from alerts.cleanup import cleanup_old_leads, close_cases_for_alerts
from alerts.gmail.gmail import GmailMessage, process_gmail_message
from alerts.models import MailboxAccount, MarketplaceAlert, ProcessedEmail


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(name="Cleanup mailbox", email="cleanup@example.local")


def create_alert(mailbox, *, listing_id: str, status: str, days_old: int = 0):
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id=listing_id,
        listing_title=f"Listing {listing_id}",
        alert_status=status,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        priority=MarketplaceAlert.Priority.NORMAL,
    )
    if days_old:
        old_at = timezone.now() - timezone.timedelta(days=days_old)
        MarketplaceAlert.objects.filter(id=alert.id).update(created_at=old_at, updated_at=old_at)
        alert.refresh_from_db()
    return alert


@pytest.mark.django_db
def test_cleanup_old_leads_does_not_delete_active_branch(mailbox):
    create_alert(
        mailbox,
        listing_id="active-1",
        status=MarketplaceAlert.AlertStatus.IGNORED,
        days_old=45,
    )
    create_alert(
        mailbox,
        listing_id="active-1",
        status=MarketplaceAlert.AlertStatus.UNREAD,
        days_old=45,
    )

    result = cleanup_old_leads(older_than_days=30)

    assert result.selected_cases == 0
    assert MarketplaceAlert.objects.filter(listing_id="active-1").count() == 2


@pytest.mark.django_db
def test_cleanup_old_leads_deletes_only_old_inactive_branches(mailbox):
    old_inactive = create_alert(
        mailbox,
        listing_id="old-inactive",
        status=MarketplaceAlert.AlertStatus.IGNORED,
        days_old=45,
    )
    create_alert(
        mailbox,
        listing_id="recent-inactive",
        status=MarketplaceAlert.AlertStatus.IGNORED,
        days_old=5,
    )

    result = cleanup_old_leads(older_than_days=30)

    assert result.selected_cases == 1
    assert result.deleted_alerts == 1
    assert not MarketplaceAlert.objects.filter(id=old_inactive.id).exists()
    assert MarketplaceAlert.objects.filter(listing_id="recent-inactive").exists()


@pytest.mark.django_db
def test_close_case_deletes_alerts_for_mailbox_and_listing_but_keeps_processed_email(mailbox):
    selected = create_alert(
        mailbox,
        listing_id="manual-1",
        status=MarketplaceAlert.AlertStatus.UNREAD,
    )
    create_alert(
        mailbox,
        listing_id="manual-1",
        status=MarketplaceAlert.AlertStatus.IN_WORK,
    )
    other_mailbox = MailboxAccount.objects.create(name="Other mailbox", email="other@example.local")
    create_alert(
        other_mailbox,
        listing_id="manual-1",
        status=MarketplaceAlert.AlertStatus.UNREAD,
    )
    ProcessedEmail.objects.create(
        mailbox=mailbox,
        gmail_message_id="gmail-manual-1",
        subject="Already processed",
    )

    result = close_cases_for_alerts(MarketplaceAlert.objects.filter(id=selected.id))

    assert result.selected_cases == 1
    assert result.deleted_alerts == 2
    assert not MarketplaceAlert.objects.filter(mailbox=mailbox, listing_id="manual-1").exists()
    assert MarketplaceAlert.objects.filter(mailbox=other_mailbox, listing_id="manual-1").exists()
    assert ProcessedEmail.objects.filter(mailbox=mailbox, gmail_message_id="gmail-manual-1").exists()


@pytest.mark.django_db
def test_old_email_does_not_recreate_alert_after_case_close(mailbox):
    message = GmailMessage(
        message_id="gmail-old-1",
        thread_id="thread-old-1",
        subject='Neue Nachricht von Max zu "BMW 320d"',
        body="Von: Max\nNachricht: Hallo\nAnzeigen-ID: 123456789",
    )
    first = process_gmail_message(mailbox, message)
    close_cases_for_alerts(MarketplaceAlert.objects.filter(id=first.alert.id))

    second = process_gmail_message(mailbox, message)

    assert second.duplicate is True
    assert second.created is False
    assert MarketplaceAlert.objects.count() == 0
    assert ProcessedEmail.objects.filter(mailbox=mailbox, gmail_message_id="gmail-old-1").exists()


@pytest.mark.django_db
def test_cleanup_old_leads_command_supports_dry_run(mailbox):
    create_alert(
        mailbox,
        listing_id="dry-run-1",
        status=MarketplaceAlert.AlertStatus.IGNORED,
        days_old=45,
    )
    stdout = StringIO()

    call_command("cleanup_old_leads", "--days", "30", "--dry-run", stdout=stdout)

    assert "Old inactive branches matched: 1" in stdout.getvalue()
    assert MarketplaceAlert.objects.filter(listing_id="dry-run-1").exists()
