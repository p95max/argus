import asyncio

import pytest

from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.telegram.sender import (
    async_send_telegram_alert,
    async_send_telegram_reminder,
    async_send_telegram_reminder_report,
    send_system_telegram_message,
)


class FakeTelegramMessage:
    message_id = 654


class FakeTelegramBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return FakeTelegramMessage()


class BrokenTelegramBot:
    async def send_message(self, **kwargs):
        raise RuntimeError("telegram is down")


@pytest.fixture
def alert(db):
    mailbox = MailboxAccount.objects.create(name="Inbox", email="inbox@example.local")
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        buyer_name="Max",
        listing_title="BMW 320d Touring",
        message_text="Ich kann heute zur Besichtigung kommen.",
        priority=MarketplaceAlert.Priority.HIGH,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
    )


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_alert_skips_noise(alert):
    alert.event_type = MarketplaceAlert.EventType.NOISE
    alert.save(update_fields=["event_type", "updated_at"])
    bot = FakeTelegramBot()

    result = asyncio.run(
        async_send_telegram_alert(
            alert,
            chat_id="42",
            bot=bot,
        )
    )

    assert result is None
    assert bot.calls == []


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_alert_requires_default_chat(monkeypatch, alert):
    monkeypatch.delenv("TELEGRAM_DEFAULT_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(ValueError, match="TELEGRAM_DEFAULT_CHAT_ID"):
        asyncio.run(
            async_send_telegram_alert(
                alert,
                bot=FakeTelegramBot(),
            )
        )


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_alert_requires_token_when_bot_is_not_injected(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        asyncio.run(async_send_telegram_alert(alert))


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_saves_last_reminded_at(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    bot = FakeTelegramBot()

    message = asyncio.run(
        async_send_telegram_reminder(
            alert,
            chat_id="42",
            bot=bot,
        )
    )

    alert.refresh_from_db()
    assert message.message_id == 654
    assert bot.calls[0]["chat_id"] == "42"
    assert bot.calls[0]["reply_markup"] is not None
    assert alert.last_reminded_at is not None
    assert alert.telegram_error == ""


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_skips_noise(alert):
    alert.event_type = MarketplaceAlert.EventType.NOISE
    alert.save(update_fields=["event_type", "updated_at"])
    bot = FakeTelegramBot()

    result = asyncio.run(
        async_send_telegram_reminder(
            alert,
            chat_id="42",
            bot=bot,
        )
    )

    alert.refresh_from_db()
    assert result is None
    assert bot.calls == []
    assert alert.last_reminded_at is None


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_report_saves_success_for_all_alerts(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    second = MarketplaceAlert.objects.create(
        mailbox=alert.mailbox,
        buyer_name="Anna",
        listing_title="VW Golf",
        message_text="Noch da?",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
    )
    bot = FakeTelegramBot()

    message = asyncio.run(
        async_send_telegram_reminder_report(
            [alert, second],
            chat_id="42",
            bot=bot,
        )
    )

    alert.refresh_from_db()
    second.refresh_from_db()
    assert message.message_id == 654
    assert bot.calls[0]["chat_id"] == "42"
    assert "Argus: непрочитанные обращения" in bot.calls[0]["text"]
    assert alert.last_reminded_at is not None
    assert second.last_reminded_at is not None
    assert alert.telegram_error == ""
    assert second.telegram_error == ""


def test_async_send_telegram_reminder_report_skips_empty_list():
    bot = FakeTelegramBot()

    result = asyncio.run(
        async_send_telegram_reminder_report(
            [],
            chat_id="42",
            bot=bot,
        )
    )

    assert result is None
    assert bot.calls == []


def test_send_system_telegram_message_requires_default_chat(monkeypatch):
    monkeypatch.delenv("TELEGRAM_DEFAULT_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(ValueError, match="TELEGRAM_DEFAULT_CHAT_ID"):
        asyncio.run(
            send_system_telegram_message(
                "Health",
                bot=FakeTelegramBot(),
            )
        )


def test_send_system_telegram_message_rejects_disallowed_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(PermissionError, match="Telegram chat is not allowed"):
        asyncio.run(
            send_system_telegram_message(
                "Health",
                chat_id="99",
                bot=FakeTelegramBot(),
            )
        )


def test_send_system_telegram_message_reraises_bot_errors(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(RuntimeError, match="telegram is down"):
        asyncio.run(
            send_system_telegram_message(
                "Health",
                chat_id="42",
                bot=BrokenTelegramBot(),
            )
        )
