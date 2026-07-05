import base64

import pytest

from alerts.gmail.gmail import GmailMessage, check_mailbox, parse_gmail_api_message, process_gmail_message
from alerts.models import LeadFlag, MailboxAccount, MarketplaceAlert, ProcessedEmail, ServiceEvent
from alerts.seed_data import seed_lead_flags


def encode_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(
        name="Test mailbox",
        email="test@example.local",
        gmail_search_query="from:(kleinanzeigen.de)",
    )


def test_parse_gmail_api_message_prefers_plain_text():
    payload = {
        "id": "msg-1",
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": 'Neue Nachricht von Max zu "BMW 320d"'},
                {"name": "Date", "value": "Fri, 03 Jul 2026 09:00:00 +0200"},
            ],
            "parts": [
                {"mimeType": "text/html", "body": {"data": encode_body("<p>HTML</p>")}},
                {"mimeType": "text/plain", "body": {"data": encode_body("Plain body")}},
            ],
        },
    }

    message = parse_gmail_api_message(payload)

    assert message.message_id == "msg-1"
    assert message.thread_id == "thread-1"
    assert message.subject == 'Neue Nachricht von Max zu "BMW 320d"'
    assert message.body == "Plain body"
    assert message.received_at is not None


@pytest.mark.django_db
def test_process_gmail_message_creates_alert_and_processed_email(mailbox):
    seed_lead_flags()
    message = GmailMessage(
        message_id="gmail-1",
        thread_id="thread-1",
        subject='Neue Nachricht von Max zu "BMW 320d"',
        body="Von: Max\nNachricht: Ich kann heute zur Besichtigung kommen.\nAnzeigen-ID: 123456789",
    )

    result = process_gmail_message(mailbox, message)

    assert result.created is True
    assert result.duplicate is False
    assert MarketplaceAlert.objects.count() == 1
    assert ProcessedEmail.objects.count() == 1

    alert = MarketplaceAlert.objects.get()
    assert alert.gmail_message_id == "gmail-1"
    assert alert.priority == MarketplaceAlert.Priority.HIGH
    assert alert.flags.filter(code="inspection_request").exists()
    assert ProcessedEmail.objects.get().gmail_message_id == "gmail-1"


@pytest.mark.django_db
def test_process_gmail_message_skips_duplicate(mailbox):
    message = GmailMessage(
        message_id="gmail-dup",
        thread_id="thread-dup",
        subject='Neue Nachricht von Max zu "BMW 320d"',
        body="Von: Max\nNachricht: Hallo\nAnzeigen-ID: 123456789",
    )

    first = process_gmail_message(mailbox, message)
    second = process_gmail_message(mailbox, message)

    assert first.created is True
    assert second.duplicate is True
    assert MarketplaceAlert.objects.count() == 1
    assert ProcessedEmail.objects.count() == 1


@pytest.mark.django_db
def test_check_mailbox_updates_success_health(mailbox):
    result = check_mailbox(
        mailbox,
        messages=[
            GmailMessage(
                message_id="gmail-health",
                thread_id="thread-health",
                subject='Neue Nachricht von Anna zu "Audi A4"',
                body="Von: Anna\nNachricht: Noch verfügbar?\nAnzeigen-ID: 777888999",
            )
        ],
    )

    mailbox.refresh_from_db()
    assert result.fetched == 1
    assert result.created == 1
    assert result.duplicates == 0
    assert mailbox.connection_status == MailboxAccount.ConnectionStatus.CONNECTED
    assert mailbox.last_checked_at is not None
    assert mailbox.last_success_at is not None
    assert mailbox.last_error == ""


@pytest.mark.django_db
def test_check_mailbox_sends_telegram_when_enabled(monkeypatch, mailbox):
    sent = []
    monkeypatch.setenv("TELEGRAM_SEND_ON_GMAIL_CHECK", "True")
    monkeypatch.setattr("alerts.telegram.sender.send_telegram_alert", lambda alert: sent.append(alert.id))

    check_mailbox(
        mailbox,
        messages=[
            GmailMessage(
                message_id="gmail-telegram",
                thread_id="thread-telegram",
                subject='Neue Nachricht von Anna zu "Audi A4"',
                body="Von: Anna\nNachricht: Noch verfÃ¼gbar?\nAnzeigen-ID: 777888999",
            )
        ],
    )

    assert sent == [MarketplaceAlert.objects.get().id]


@pytest.mark.django_db
def test_check_mailbox_updates_error_health(monkeypatch, mailbox):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_DEFAULT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)

    class BrokenService:
        pass

    with pytest.raises(Exception):
        check_mailbox(mailbox, service=BrokenService())

    mailbox.refresh_from_db()
    assert mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR
    assert mailbox.last_error
    assert ServiceEvent.objects.filter(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        mailbox=mailbox,
    ).exists()
