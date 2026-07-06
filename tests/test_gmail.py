import base64

import pytest

from alerts.crypto import encrypt_text
from alerts.gmail.gmail import (
    fetch_gmail_messages,
    GmailMessage,
    check_mailbox,
    load_or_refresh_mailbox_credentials,
    parse_gmail_api_message,
    process_gmail_message,
)
from alerts.models import MailboxAccount, MarketplaceAlert, ProcessedEmail, ServiceEvent
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


def test_fetch_gmail_messages_uses_batch_api_when_available():
    class FakeRequest:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class FakeMessagesApi:
        def __init__(self, service):
            self.service = service

        def list(self, **kwargs):
            return FakeRequest({"messages": [{"id": "msg-1"}, {"id": "msg-2"}]})

        def get(self, **kwargs):
            message_id = kwargs["id"]
            self.service.single_get_execute_count += 1
            return FakeRequest(
                {
                    "id": message_id,
                    "threadId": f"thread-{message_id}",
                    "payload": {"headers": [], "body": {"data": encode_body("Body")}},
                }
            )

    class FakeUsersApi:
        def __init__(self, service):
            self.service = service

        def messages(self):
            return FakeMessagesApi(self.service)

    class FakeBatch:
        def __init__(self, callback):
            self.callback = callback
            self.requests = []

        def add(self, request, request_id):
            self.requests.append((request_id, request))

        def execute(self):
            for request_id, request in self.requests:
                self.callback(request_id, request.payload, None)

    class FakeService:
        def __init__(self):
            self.batch_requests = []
            self.single_get_execute_count = 0

        def users(self):
            return FakeUsersApi(self)

        def new_batch_http_request(self, callback):
            batch = FakeBatch(callback)
            self.batch_requests.append(batch)
            return batch

    service = FakeService()

    messages = fetch_gmail_messages(service, "from:(kleinanzeigen.de)", max_results=2)

    assert [message.message_id for message in messages] == ["msg-1", "msg-2"]
    assert len(service.batch_requests) == 1
    assert len(service.batch_requests[0].requests) == 2


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
def test_check_mailbox_does_not_send_noise_to_telegram(monkeypatch, mailbox):
    sent = []
    monkeypatch.setenv("TELEGRAM_SEND_ON_GMAIL_CHECK", "True")
    monkeypatch.setattr("alerts.telegram.sender.send_telegram_alert", lambda alert: sent.append(alert.id))

    result = check_mailbox(
        mailbox,
        messages=[
            GmailMessage(
                message_id="gmail-noise",
                thread_id="thread-noise",
                subject="Kleinanzeigen Newsletter",
                body="Newsletter: neue Angebote, Rabatt und Tipps von Kleinanzeigen.",
            )
        ],
    )

    alert = MarketplaceAlert.objects.get()
    assert result.created == 1
    assert sent == []
    assert alert.event_type == MarketplaceAlert.EventType.NOISE
    assert alert.priority == MarketplaceAlert.Priority.LOW


@pytest.mark.django_db
def test_check_mailbox_sends_listing_expiration_as_operational_event(monkeypatch, mailbox):
    sent = []
    monkeypatch.setenv("TELEGRAM_SEND_ON_GMAIL_CHECK", "True")
    monkeypatch.setattr("alerts.telegram.sender.send_telegram_alert", lambda alert: sent.append(alert.id))

    result = check_mailbox(
        mailbox,
        messages=[
            GmailMessage(
                message_id="gmail-expiring",
                thread_id="thread-expiring",
                subject='Deine Anzeige "VW Golf GTI" läuft bald ab',
                body="Deine Anzeige läuft bald ab.\nAnzeigen-ID: 987654321",
            )
        ],
    )

    alert = MarketplaceAlert.objects.get()
    assert result.created == 1
    assert sent == [alert.id]
    assert alert.event_type == MarketplaceAlert.EventType.LISTING_EXPIRING
    assert alert.buyer_name == ""


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


@pytest.mark.django_db
def test_load_mailbox_credentials_accepts_plaintext_legacy_token(monkeypatch, mailbox):
    calls = []

    class FakeCredentials:
        valid = True

        @classmethod
        def from_authorized_user_info(cls, token_info, scopes):
            calls.append(token_info)
            return cls()

    monkeypatch.setattr("alerts.gmail.gmail.Credentials", FakeCredentials)
    mailbox.gmail_oauth_token = '{"token": "legacy-access-token"}'
    mailbox.save(update_fields=["gmail_oauth_token", "updated_at"])

    credentials = load_or_refresh_mailbox_credentials(mailbox)

    assert credentials.valid is True
    assert calls == [{"token": "legacy-access-token"}]


@pytest.mark.django_db
def test_load_mailbox_credentials_decrypts_encrypted_token(monkeypatch, mailbox):
    calls = []

    class FakeCredentials:
        valid = True

        @classmethod
        def from_authorized_user_info(cls, token_info, scopes):
            calls.append(token_info)
            return cls()

    monkeypatch.setattr("alerts.gmail.gmail.Credentials", FakeCredentials)
    mailbox.gmail_oauth_token = encrypt_text('{"token": "encrypted-access-token"}')
    mailbox.save(update_fields=["gmail_oauth_token", "updated_at"])

    credentials = load_or_refresh_mailbox_credentials(mailbox)

    assert credentials.valid is True
    assert calls == [{"token": "encrypted-access-token"}]
