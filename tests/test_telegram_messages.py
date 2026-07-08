from django.utils import timezone

from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.telegram.messages import (
    TELEGRAM_SAFE_MESSAGE_LIMIT,
    _truncate_html_message,
    build_alert_message,
    build_alert_reminder_message,
    build_system_message,
)


def test_build_alert_message_caps_escaped_body_text():
    alert = _make_alert(message_text="&" * 1200)

    message = build_alert_message(alert)

    assert len(message) <= TELEGRAM_SAFE_MESSAGE_LIMIT
    assert message.endswith("...")
    assert _does_not_end_inside_html_entity(message)


def test_build_alert_reminder_message_caps_prefixed_text():
    alert = _make_alert(message_text="&" * 1200)

    message = build_alert_reminder_message(alert)

    assert len(message) <= TELEGRAM_SAFE_MESSAGE_LIMIT
    assert message.startswith("⏰ <b>Reminder")
    assert _does_not_end_inside_html_entity(message)


def test_build_system_message_caps_escaped_details():
    message = build_system_message("Ошибка", details="&" * 1200)

    assert len(message) <= TELEGRAM_SAFE_MESSAGE_LIMIT
    assert message.endswith("...")
    assert _does_not_end_inside_html_entity(message)


def test_truncate_html_message_drops_incomplete_entity_before_suffix():
    source = "A" * (TELEGRAM_SAFE_MESSAGE_LIMIT - 4) + "&amp;tail"

    message = _truncate_html_message(source)

    assert len(message) <= TELEGRAM_SAFE_MESSAGE_LIMIT
    assert message.endswith("...")
    assert _does_not_end_inside_html_entity(message)


def _make_alert(message_text: str) -> MarketplaceAlert:
    now = timezone.now()
    mailbox = MailboxAccount(name="Demo", email="demo@example.com")
    alert = MarketplaceAlert(
        id=123,
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        priority=MarketplaceAlert.Priority.HIGH,
        parse_status=MarketplaceAlert.ParseStatus.SUCCESS,
        listing_title="VW Golf",
        buyer_name="Buyer",
        message_text=message_text,
        received_at=now,
        created_at=now,
        processed_at=now,
    )
    alert._telegram_flag_names = "нет"
    alert._telegram_mailbox_label = "Demo (demo@example.com)"
    return alert


def _does_not_end_inside_html_entity(value: str) -> bool:
    body = value.removesuffix("...")
    last_ampersand = body.rfind("&")
    last_semicolon = body.rfind(";")
    return last_ampersand <= last_semicolon
