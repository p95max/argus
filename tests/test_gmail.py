import base64

import pytest
from googleapiclient.errors import HttpError

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


def test_fetch_gmail_messages_fetches_payloads_sequentially():
    class FakeRequest:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class FakeMessagesApi:
        def __init__(self, service):
            self.service = service

        def list(self, **kwargs):
            self.service.list_kwargs = kwargs
            return FakeRequest({"messages": [{"id": "msg-1"}, {"id": "msg-2"}]})

        def get(self, **kwargs):
            message_id = kwargs["id"]
            self.service.get_message_ids.append(message_id)
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

    class FakeService:
        def __init__(self):
            self.list_kwargs = {}
            self.get_message_ids = []
            self.single_get_execute_count = 0

        def users(self):
            return FakeUsersApi(self)

    service = FakeService()

    messages = fetch_gmail_messages(service, "from:(kleinanzeigen.de)", max_results=2)

    assert service.list_kwargs["userId"] == "me"
    assert service.list_kwargs["q"] == "from:(kleinanzeigen.de)"
    assert service.list_kwargs["maxResults"] == 2
    assert [message.message_id for message in messages] == ["msg-1", "msg-2"]
    assert service.get_message_ids == ["msg-1", "msg-2"]
    assert service.single_get_execute_count == 2


def test_fetch_gmail_messages_retries_retryable_list_error(monkeypatch):
    class Response(dict):
        status = 429
        reason = "Too Many Requests"

    class FlakyRequest:
        def __init__(self, payload):
            self.payload = payload
            self.calls = 0

        def execute(self):
            self.calls += 1
            if self.calls == 1:
                raise HttpError(Response(), b"{}")
            return self.payload

    class FakeMessagesApi:
        def __init__(self, service):
            self.service = service

        def list(self, **kwargs):
            self.service.list_request = FlakyRequest({"messages": []})
            return self.service.list_request

    class FakeUsersApi:
        def __init__(self, service):
            self.service = service

        def messages(self):
            return FakeMessagesApi(self.service)

    class FakeService:
        def users(self):
            return FakeUsersApi(self)

    sleep_calls = []
    monkeypatch.setattr("alerts.gmail.gmail.time.sleep", lambda seconds: sleep_calls.append(seconds))
    service = FakeService()

    messages = fetch_gmail_messages(service, "from:(kleinanzeigen.de)", max_results=2)

    assert messages == []
    assert service.list_request.calls == 2
    assert sleep_calls == [1.0]


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


@pytest.mark.django_db
def test_load_mailbox_credentials_marks_invalid_stored_token_as_error(mailbox):
    mailbox.gmail_oauth_token = encrypt_text("not-json")
    mailbox.save(update_fields=["gmail_oauth_token", "updated_at"])

    with pytest.raises(RuntimeError, match="cannot be decrypted or is not valid JSON"):
        load_or_refresh_mailbox_credentials(mailbox)

    mailbox.refresh_from_db()
    assert mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR
    assert mailbox.gmail_oauth_error == "Stored Gmail OAuth token cannot be decrypted or is not valid JSON."
    assert mailbox.last_error == mailbox.gmail_oauth_error


@pytest.mark.django_db
def test_load_mailbox_credentials_refreshes_expired_token(monkeypatch, mailbox):
    class FakeCredentials:
        valid = False
        expired = True
        refresh_token = "refresh-token"

        @classmethod
        def from_authorized_user_info(cls, token_info, scopes):
            return cls()

        def refresh(self, request):
            self.valid = True

        def to_json(self):
            return '{"token": "new-access-token"}'

    monkeypatch.setattr("alerts.gmail.gmail.Credentials", FakeCredentials)
    mailbox.gmail_oauth_token = encrypt_text('{"token": "old-access-token", "refresh_token": "refresh-token"}')
    mailbox.gmail_oauth_error = "old error"
    mailbox.last_error = "old error"
    mailbox.save(update_fields=["gmail_oauth_token", "gmail_oauth_error", "last_error", "updated_at"])

    credentials = load_or_refresh_mailbox_credentials(mailbox)

    mailbox.refresh_from_db()
    assert credentials.valid is True
    assert mailbox.gmail_oauth_last_refresh_at is not None
    assert mailbox.gmail_oauth_error == ""
    assert mailbox.last_error == ""
    assert "fernet:" in mailbox.gmail_oauth_token
