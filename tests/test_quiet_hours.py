import asyncio
from datetime import datetime, time

import pytest
from django.utils import timezone

from alerts.models import MailboxAccount, MarketplaceAlert, TelegramSettings
from alerts.telegram.messages import should_send_telegram_for_alert
from alerts.telegram.quiet_hours import is_quiet_hours_now
from alerts.telegram.sender import async_send_telegram_alert


class FakeTelegramMessage:
    message_id = 987


class FakeTelegramBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return FakeTelegramMessage()


@pytest.fixture
def alert(db):
    mailbox = MailboxAccount.objects.create(name="Quiet inbox", email="quiet@example.local")
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        buyer_name="Max",
        listing_title="BMW 320d",
        message_text="Noch da?",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        priority=MarketplaceAlert.Priority.NORMAL,
    )


def aware(hour: int, minute: int = 0):
    return timezone.make_aware(datetime(2026, 7, 5, hour, minute))


@pytest.mark.django_db
def test_quiet_hours_are_disabled_by_default(alert):
    assert TelegramSettings.objects.count() == 0

    assert should_send_telegram_for_alert(alert, at_time=aware(23)) is True

    settings = TelegramSettings.objects.get()
    assert settings.quiet_hours_enabled is False
    assert settings.quiet_hours_start == time(22, 0)
    assert settings.quiet_hours_end == time(7, 0)
    assert settings.allow_urgent_during_quiet_hours is False


@pytest.mark.django_db
def test_quiet_hours_block_normal_alerts_at_night(alert):
    settings = TelegramSettings.objects.create(quiet_hours_enabled=True)

    assert is_quiet_hours_now(at_time=aware(23), settings=settings) is True
    assert should_send_telegram_for_alert(alert, at_time=aware(23)) is False


@pytest.mark.django_db
def test_quiet_hours_do_not_block_normal_alerts_during_day(alert):
    TelegramSettings.objects.create(quiet_hours_enabled=True)

    assert should_send_telegram_for_alert(alert, at_time=aware(12)) is True


@pytest.mark.django_db
def test_quiet_hours_can_allow_urgent_alerts(alert):
    settings = TelegramSettings.objects.create(
        quiet_hours_enabled=True,
        allow_urgent_during_quiet_hours=True,
    )
    alert.priority = MarketplaceAlert.Priority.URGENT
    alert.save(update_fields=["priority", "updated_at"])

    assert is_quiet_hours_now(at_time=aware(23), settings=settings) is True
    assert should_send_telegram_for_alert(alert, at_time=aware(23)) is True


@pytest.mark.django_db
def test_quiet_hours_block_urgent_alerts_without_exception(alert):
    TelegramSettings.objects.create(quiet_hours_enabled=True)
    alert.priority = MarketplaceAlert.Priority.URGENT
    alert.save(update_fields=["priority", "updated_at"])

    assert should_send_telegram_for_alert(alert, at_time=aware(23)) is False


@pytest.mark.django_db
def test_quiet_hours_still_skip_noise(alert):
    TelegramSettings.objects.create(
        quiet_hours_enabled=True,
        allow_urgent_during_quiet_hours=True,
    )
    alert.event_type = MarketplaceAlert.EventType.NOISE
    alert.priority = MarketplaceAlert.Priority.URGENT
    alert.save(update_fields=["event_type", "priority", "updated_at"])

    assert should_send_telegram_for_alert(alert, at_time=aware(12)) is False


@pytest.mark.django_db(transaction=True)
def test_sender_skips_normal_alert_during_quiet_hours(alert):
    TelegramSettings.objects.create(
        quiet_hours_enabled=True,
        quiet_hours_start=time(0, 0),
        quiet_hours_end=time(0, 0),
    )
    bot = FakeTelegramBot()

    result = asyncio.run(async_send_telegram_alert(alert, chat_id="42", bot=bot))

    alert.refresh_from_db()
    assert result is None
    assert bot.calls == []
    assert alert.telegram_sent_at is None


@pytest.mark.django_db(transaction=True)
def test_sender_allows_urgent_alert_during_quiet_hours_when_enabled(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    TelegramSettings.objects.create(
        quiet_hours_enabled=True,
        quiet_hours_start=time(0, 0),
        quiet_hours_end=time(0, 0),
        allow_urgent_during_quiet_hours=True,
    )
    alert.priority = MarketplaceAlert.Priority.URGENT
    alert.save(update_fields=["priority", "updated_at"])
    bot = FakeTelegramBot()

    result = asyncio.run(async_send_telegram_alert(alert, chat_id="42", bot=bot))

    alert.refresh_from_db()
    assert result is not None
    assert len(bot.calls) == 1
    assert alert.telegram_sent_at is not None
