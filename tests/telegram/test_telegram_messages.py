from datetime import timedelta

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
    assert message.startswith("⏰ <b>Argus: unread leads</b>")
    assert "🔴 <b>Status:</b> needs attention" in message
    assert "🆕 <b>Unread:</b> 2" in message
    assert "📂 <b>Cases:</b> 2" in message
    assert "🔥 <b>High/Urgent:</b> 1" in message
    assert "📱 <a" in message


def test_build_unread_reminder_report_rounds_oldest_age():
    alert = _make_alert(message_text="Noch da?")
    alert.created_at = timezone.now() - timedelta(minutes=1199)

    message = build_unread_reminder_report_message([alert])

    assert "⏳ <b>Oldest:</b> 20 h" in message
    assert "⏳ 20 h" in message
    assert "1199 min" not in message


def test_build_unread_reminder_report_uses_latest_known_buyer_in_case():
    older = _make_alert(message_text="Noch da?")
    older.id = 201
    older.listing_id = "case-1"
    older.buyer_name = "Max"
    older.created_at = timezone.now() - timedelta(hours=2)
    newer = _make_alert(message_text="Kann ich kommen?")
    newer.id = 202
    newer.listing_id = "case-1"
    newer.buyer_name = ""
    newer.created_at = timezone.now() - timedelta(hours=1)

    message = build_unread_reminder_report_message([older, newer])

    assert "👤 <b>Latest:</b> Max" in message
    assert "unknown" not in message


def test_build_unread_reminder_report_infers_interested_buyer_from_subject():
    alert = _make_alert(message_text="Guten Tag")
    alert.buyer_name = ""
    alert.subject = 'Re: Nutzer-Anfrage zu deiner Anzeige "AUDI A3"'

    message = build_unread_reminder_report_message([alert])

    assert "👤 <b>Latest:</b> Interessent" in message


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
