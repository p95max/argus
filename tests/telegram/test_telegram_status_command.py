import pytest

from alerts.mobile_listings import LISTING_CLOSED_MARKER
from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.telegram.status_command import (
    build_ads_status_keyboard,
    build_ads_status_message,
    build_mailboxes_status_message,
)


@pytest.mark.django_db
def test_mailboxes_status_message_contains_only_mailbox_status():
    MailboxAccount.objects.create(
        name="Main",
        email="main@example.com",
        connection_status=MailboxAccount.ConnectionStatus.CONNECTED,
    )

    message = build_mailboxes_status_message()

    assert "Mailbox status" in message
    assert "Main" in message
    assert "Listing:" not in message


@pytest.mark.django_db
def test_ads_status_message_contains_active_listing_stats_only():
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

    message = build_ads_status_message()

    assert "Listing: 1" in message
    assert "• VW Golf\n· 💬 2 · 🆕 1 · 🛠 1" in message
    assert "Mailbox status" not in message


@pytest.mark.django_db
def test_ads_status_message_excludes_closed_listing():
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

    message = build_ads_status_message()

    assert "Listing: 1" in message
    assert "Active car" in message
    assert "Closed car" not in message


def test_ads_status_keyboard_links_to_mobile_listings(settings):
    settings.ARGUS_PUBLIC_BASE_URL = "https://argus.example.com"

    keyboard = build_ads_status_keyboard()

    assert keyboard is not None
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "🚗 Объявления"
    assert button.url == "https://argus.example.com/m/listings/"


def test_ads_status_keyboard_is_hidden_without_public_base_url(settings):
    settings.ARGUS_PUBLIC_BASE_URL = ""

    assert build_ads_status_keyboard() is None
