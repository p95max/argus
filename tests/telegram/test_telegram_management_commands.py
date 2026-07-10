from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from alerts.models import MailboxAccount, MarketplaceAlert


class FakeTelegramMessage:
    message_id = 4321


@pytest.fixture
def alert(db):
    mailbox = MailboxAccount.objects.create(name="Inbox", email="inbox@example.local")
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_title="BMW 320d",
        message_text="Is it still available?",
    )


@pytest.mark.django_db
def test_send_telegram_alert_command_sends_alert(monkeypatch, alert):
    sent = []

    def fake_send_telegram_alert(alert_obj, chat_id=None):
        sent.append((alert_obj.id, chat_id))
        alert_obj.telegram_chat_id = chat_id or "default-chat"
        return FakeTelegramMessage()

    monkeypatch.setattr(
        "alerts.management.commands.send_telegram_alert.send_telegram_alert",
        fake_send_telegram_alert,
    )
    stdout = StringIO()

    call_command("send_telegram_alert", alert.id, "--chat-id", "42", stdout=stdout)

    assert sent == [(alert.id, "42")]
    assert f"Telegram alert sent for alert {alert.id}" in stdout.getvalue()
    assert "message_id=4321" in stdout.getvalue()


@pytest.mark.django_db
def test_send_telegram_alert_command_reports_skipped_alert(monkeypatch, alert):
    monkeypatch.setattr(
        "alerts.management.commands.send_telegram_alert.send_telegram_alert",
        lambda alert_obj, chat_id=None: None,
    )
    stdout = StringIO()

    call_command("send_telegram_alert", alert.id, stdout=stdout)

    assert f"Telegram alert skipped for alert {alert.id}." in stdout.getvalue()


@pytest.mark.django_db
def test_send_telegram_alert_command_rejects_missing_alert():
    with pytest.raises(CommandError, match="Alert 999 was not found"):
        call_command("send_telegram_alert", 999)


@pytest.mark.django_db
def test_send_telegram_alert_command_wraps_send_error(monkeypatch, alert):
    def broken_send(alert_obj, chat_id=None):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(
        "alerts.management.commands.send_telegram_alert.send_telegram_alert",
        broken_send,
    )

    with pytest.raises(CommandError, match="telegram down"):
        call_command("send_telegram_alert", alert.id)


def test_send_telegram_system_command_sends_message(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "alerts.management.commands.send_telegram_system.send_system_telegram_alert",
        lambda title, details="", chat_id=None: sent.append((title, details, chat_id)),
    )
    stdout = StringIO()

    call_command(
        "send_telegram_system",
        "Deploy finished",
        "--details",
        "ok",
        "--chat-id",
        "42",
        stdout=stdout,
    )

    assert sent == [("Deploy finished", "ok", "42")]
    assert "Telegram system message sent." in stdout.getvalue()


def test_send_telegram_system_command_wraps_send_error(monkeypatch):
    def broken_send(title, details="", chat_id=None):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(
        "alerts.management.commands.send_telegram_system.send_system_telegram_alert",
        broken_send,
    )

    with pytest.raises(CommandError, match="telegram down"):
        call_command("send_telegram_system", "Deploy failed")


def test_connect_gmail_command_runs_local_oauth(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "alerts.management.commands.connect_gmail.gmail_credentials_paths",
        lambda: ("credentials.json", "token.json"),
    )
    monkeypatch.setattr(
        "alerts.management.commands.connect_gmail.connect_gmail",
        lambda credentials_file, token_file, port: calls.append((credentials_file, token_file, port))
        or "token.json",
    )
    stdout = StringIO()

    call_command("connect_gmail", "--port", "8787", stdout=stdout)

    assert calls == [("credentials.json", "token.json", 8787)]
    assert "Gmail token saved to token.json" in stdout.getvalue()

