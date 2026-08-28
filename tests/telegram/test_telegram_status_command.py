import pytest

from alerts.mobile_listings import LISTING_CLOSED_MARKER
from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.telegram.status_command import build_status_message


@pytest.mark.django_db
def test_status_message_has_mailboxes_and_active_listing_stats():
    mailbox = MailboxAccount.objects.create(
        name="Main",
        email="main@example.com",
        connection_status=MailboxAccount.ConnectionStatus.CONNECTED,
    )
    MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="123",
        listing_title="VW Golf",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
    )
    MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="123",
        listing_title="VW Golf",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.IN_WORK,
    )

    message = build_status_message()

    assert "Mailbox status" in message
    assert "Main" in message
    assert "Listing: 1" in message
    assert "VW Golf" in message
    assert "💬 2" in message
    assert "🆕 1" in message
    assert "🛠 1" in message


@pytest.mark.django_db
def test_status_message_excludes_closed_listing():
    mailbox = MailboxAccount.objects.create(
        name="Main",
        email="main@example.com",
        connection_status=MailboxAccount.ConnectionStatus.CONNECTED,
    )
    MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="closed-1",
        listing_title="Closed car",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.ARCHIVED,
        taken_by_label=LISTING_CLOSED_MARKER,
    )
    MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="active-1",
        listing_title="Active car",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.ARCHIVED,
    )

    message = build_status_message()

    assert "Listing: 1" in message
    assert "Active car" in message
    assert "Closed car" not in message
