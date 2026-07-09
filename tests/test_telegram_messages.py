from django.utils import timezone

from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.telegram.messages import (
    TELEGRAM_SAFE_MESSAGE_LIMIT,
    _truncate_html_message,
    build_alert_message,
    build_alert_reminder_message,
    build_system_message,
    build_unread_reminder_report_message,
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


def test_build_unread_reminder_report_uses_telegram_alert_style():
    first = _make_alert(message_text="Noch da?")
    first.id = 201
    first.listing_id = "case-1"
    first.listing_title = "BMW 320d"
    first.buyer_name = "Max"
    first.priority = MarketplaceAlert.Priority.HIGH
    second = _make_alert(message_text="Kann ich kommen?")
    second.id = 202
    second.listing_id = "case-2"
    second.listing_title = "VW Golf"
    second.buyer_name = "Anna"
    second.priority = MarketplaceAlert.Priority.NORMAL

    message = build_unread_reminder_report_message([first, second])

    assert len(message) <= TELEGRAM_SAFE_MESSAGE_LIMIT
    assert message.startswith("⏰ <b>Argus: непрочитанные обращения</b>")
    assert "🔴 <b>Статус:</b> требуется внимание" in message
    assert "🆕 <b>Непрочитано:</b> 2" in message
    assert "📂 <b>Кейсов:</b> 2" in message
    assert "🔥 <b>High/Urgent:</b> 1" in message
    assert "📱 <a" in message


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
