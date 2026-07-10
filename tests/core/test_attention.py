import pytest

from alerts.attention import alert_needs_attention, filter_needs_attention
from alerts.models import MailboxAccount, MarketplaceAlert


def make_alert(mailbox, **kwargs):
    defaults = {
        "mailbox": mailbox,
        "listing_title": "BMW 320d",
        "alert_status": MarketplaceAlert.AlertStatus.IN_WORK,
        "priority": MarketplaceAlert.Priority.NORMAL,
        "parse_status": MarketplaceAlert.ParseStatus.SUCCESS,
    }
    defaults.update(kwargs)
    return MarketplaceAlert.objects.create(**defaults)


@pytest.mark.django_db
def test_alert_needs_attention_matches_unread_priority_parse_and_connection_states():
    mailbox = MailboxAccount.objects.create(name="Inbox", email="inbox@example.local")
    error_mailbox = MailboxAccount.objects.create(
        name="Broken",
        email="broken@example.local",
        connection_status=MailboxAccount.ConnectionStatus.ERROR,
    )

    unread = make_alert(mailbox, alert_status=MarketplaceAlert.AlertStatus.UNREAD)
    high = make_alert(mailbox, priority=MarketplaceAlert.Priority.HIGH)
    parse_error = make_alert(mailbox, parse_status=MarketplaceAlert.ParseStatus.ERROR)
    telegram_error = make_alert(mailbox, telegram_error="send failed")
    mailbox_error = make_alert(error_mailbox)
    ignored = make_alert(
        mailbox,
        alert_status=MarketplaceAlert.AlertStatus.IGNORED,
        priority=MarketplaceAlert.Priority.URGENT,
        telegram_error="ignored errors do not matter",
    )
    normal = make_alert(mailbox)

    assert alert_needs_attention(unread) is True
    assert alert_needs_attention(high) is True
    assert alert_needs_attention(parse_error) is True
    assert alert_needs_attention(telegram_error) is True
    assert alert_needs_attention(mailbox_error) is True
    assert alert_needs_attention(ignored) is False
    assert alert_needs_attention(normal) is False


@pytest.mark.django_db
def test_filter_needs_attention_returns_distinct_non_terminal_alerts():
    mailbox = MailboxAccount.objects.create(name="Inbox", email="inbox@example.local")
    unread = make_alert(mailbox, alert_status=MarketplaceAlert.AlertStatus.UNREAD)
    urgent = make_alert(mailbox, priority=MarketplaceAlert.Priority.URGENT)
    make_alert(mailbox, alert_status=MarketplaceAlert.AlertStatus.ARCHIVED, priority=MarketplaceAlert.Priority.URGENT)
    make_alert(mailbox)

    ids = set(filter_needs_attention(MarketplaceAlert.objects.all()).values_list("id", flat=True))

    assert ids == {unread.id, urgent.id}

