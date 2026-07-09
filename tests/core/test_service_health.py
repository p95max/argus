import pytest

from alerts.gmail.gmail import GmailMessage, check_mailbox, process_gmail_message
from alerts.models import MailboxAccount, MarketplaceAlert, ServiceEvent
from alerts.service_health import (
    record_mailbox_recovery,
    record_parser_error,
    record_service_event,
    record_telegram_send_error,
)


class BrokenGmailService:
    pass


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(
        name="Health mailbox",
        email="health@example.local",
        gmail_search_query="from:(kleinanzeigen.de)",
    )


@pytest.fixture
def telegram_system_messages(monkeypatch):
    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.setattr(
        "alerts.telegram.sender.send_system_telegram_alert",
        lambda title, details="": sent.append({"title": title, "details": details}),
    )
    return sent


@pytest.mark.django_db
def test_mailbox_error_records_service_event_and_sends_telegram(mailbox, telegram_system_messages):
    with pytest.raises(Exception):
        check_mailbox(mailbox, service=BrokenGmailService())

    event = ServiceEvent.objects.get(event_type=ServiceEvent.EventType.MAILBOX_ERROR)
    assert event.severity == ServiceEvent.Severity.ERROR
    assert event.status == ServiceEvent.Status.OPEN
    assert event.mailbox == mailbox
    assert event.telegram_sent_at is not None
    assert telegram_system_messages[0]["title"] == f"Mailbox error: {mailbox.email}"


@pytest.mark.django_db
def test_empty_successful_mailbox_check_does_not_create_service_noise(mailbox, telegram_system_messages):
    result = check_mailbox(mailbox, messages=[])

    assert result.fetched == 0
    assert result.created == 0
    assert ServiceEvent.objects.count() == 0
    assert telegram_system_messages == []


@pytest.mark.django_db
def test_mailbox_recovery_sends_short_notification(mailbox, telegram_system_messages):
    with pytest.raises(Exception):
        check_mailbox(mailbox, service=BrokenGmailService())

    mailbox.refresh_from_db()
    result = check_mailbox(mailbox, messages=[])

    assert result.fetched == 0
    assert ServiceEvent.objects.filter(event_type=ServiceEvent.EventType.MAILBOX_ERROR).get().status == (
        ServiceEvent.Status.RECOVERED
    )
    recovery = ServiceEvent.objects.get(event_type=ServiceEvent.EventType.RECOVERY)
    assert recovery.status == ServiceEvent.Status.RECOVERED
    assert recovery.telegram_sent_at is not None
    assert telegram_system_messages[-1]["title"] == f"Mailbox recovered: {mailbox.email}"


@pytest.mark.django_db(transaction=True)
def test_parser_partial_records_service_event(mailbox, telegram_system_messages):
    result = process_gmail_message(
        mailbox,
        GmailMessage(
            message_id="parser-partial",
            thread_id="thread-parser-partial",
            subject="Neue Nachricht von Unbekannt",
            body="Kleinanzeigen Nachricht ohne strukturierte Felder",
        ),
    )

    event = ServiceEvent.objects.get(event_type=ServiceEvent.EventType.PARSER_ERROR)
    assert result.alert.parse_status == MarketplaceAlert.ParseStatus.PARTIAL
    assert event.alert == result.alert
    assert event.severity == ServiceEvent.Severity.WARNING
    assert event.telegram_sent_at is not None
    assert "Parser" in telegram_system_messages[0]["title"]


@pytest.mark.django_db
def test_telegram_send_error_records_service_event(mailbox):
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        buyer_name="Max",
        listing_title="BMW 320d",
        message_text="Noch da?",
        priority=MarketplaceAlert.Priority.HIGH,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )

    record_telegram_send_error(alert, RuntimeError("telegram is down"))

    event = ServiceEvent.objects.get(event_type=ServiceEvent.EventType.TELEGRAM_SEND_ERROR)
    assert event.alert == alert
    assert event.severity == ServiceEvent.Severity.ERROR
    assert event.telegram_sent_at is None
    assert event.details == "telegram is down"


@pytest.mark.django_db
def test_record_service_event_deduplicates_open_event(mailbox):
    first = record_service_event(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        severity=ServiceEvent.Severity.WARNING,
        title="Gmail slow",
        details="first",
        source="gmail",
        fingerprint="gmail:slow",
        mailbox=mailbox,
        notify=False,
    )

    second = record_service_event(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        title="Gmail down",
        details="second",
        source="gmail",
        fingerprint="gmail:slow",
        mailbox=mailbox,
        notify=False,
    )

    first.refresh_from_db()
    assert second.id == first.id
    assert ServiceEvent.objects.count() == 1
    assert first.occurrences == 2
    assert first.severity == ServiceEvent.Severity.ERROR
    assert first.title == "Gmail down"
    assert first.details == "second"


@pytest.mark.django_db
def test_record_parser_error_ignores_successful_alert(mailbox):
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        parse_status=MarketplaceAlert.ParseStatus.SUCCESS,
        listing_title="BMW 320d",
    )

    assert record_parser_error(alert) is None
    assert ServiceEvent.objects.count() == 0


@pytest.mark.django_db
def test_telegram_send_error_deduplicates_by_alert(mailbox):
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        buyer_name="Max",
        listing_title="BMW 320d",
        message_text="Noch da?",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )

    first = record_telegram_send_error(alert, RuntimeError("first failure"))
    second = record_telegram_send_error(alert, RuntimeError("second failure"))

    first.refresh_from_db()
    assert second.id == first.id
    assert ServiceEvent.objects.count() == 1
    assert first.occurrences == 2
    assert first.details == "second failure"


@pytest.mark.django_db
def test_record_mailbox_recovery_without_open_error_is_noop(mailbox):
    assert record_mailbox_recovery(mailbox, previous_error="old") is None
    assert ServiceEvent.objects.count() == 0
