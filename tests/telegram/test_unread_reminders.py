import asyncio
from datetime import time, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from alerts.models import MailboxAccount, MarketplaceAlert, TelegramSettings
from alerts.reminders import unread_alerts_due_for_reminder
from alerts.telegram.sender import async_send_telegram_reminder, async_send_telegram_reminder_report


class FakeTelegramMessage:
    message_id = 654


class FakeTelegramBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return FakeTelegramMessage()


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(name="Reminder inbox", email="reminders@example.local")


def create_alert(mailbox, *, minutes_old: int, status=None, event_type=None, last_reminded_minutes_ago=None):
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        buyer_name="Max",
        listing_title="BMW 320d",
        message_text="Noch da?",
        alert_status=status or MarketplaceAlert.AlertStatus.UNREAD,
        event_type=event_type or MarketplaceAlert.EventType.BUYER_MESSAGE,
        priority=MarketplaceAlert.Priority.HIGH,
    )
    created_at = timezone.now() - timedelta(minutes=minutes_old)
    last_reminded_at = None
    if last_reminded_minutes_ago is not None:
        last_reminded_at = timezone.now() - timedelta(minutes=last_reminded_minutes_ago)

    MarketplaceAlert.objects.filter(id=alert.id).update(
        created_at=created_at,
        last_reminded_at=last_reminded_at,
    )
    alert.refresh_from_db()
    return alert


@pytest.mark.django_db
def test_unread_alerts_due_for_reminder_filters_age_status_noise_and_interval(mailbox):
    due_never_reminded = create_alert(mailbox, minutes_old=45)
    due_stale_reminder = create_alert(mailbox, minutes_old=90, last_reminded_minutes_ago=70)
    create_alert(mailbox, minutes_old=10)
    create_alert(mailbox, minutes_old=45, status=MarketplaceAlert.AlertStatus.IN_WORK)
    create_alert(mailbox, minutes_old=45, event_type=MarketplaceAlert.EventType.NOISE)
    create_alert(mailbox, minutes_old=90, last_reminded_minutes_ago=10)

    due_ids = list(
        unread_alerts_due_for_reminder(
            min_age_minutes=30,
            reminder_interval_minutes=60,
        ).values_list("id", flat=True)
    )

    assert due_ids == [due_stale_reminder.id, due_never_reminded.id]


@pytest.mark.django_db
def test_send_unread_reminders_command_sends_due_alerts_and_updates_last_reminded(
    monkeypatch,
    mailbox,
):
    sent = []
    due = create_alert(mailbox, minutes_old=45)
    due_same_case = create_alert(mailbox, minutes_old=50)
    create_alert(mailbox, minutes_old=45, last_reminded_minutes_ago=10)

    def fake_send_reminder_report(alerts):
        sent.append([alert.id for alert in alerts])
        now = timezone.now()
        for alert in alerts:
            alert.last_reminded_at = now
            alert.save(update_fields=["last_reminded_at", "updated_at"])

    monkeypatch.setattr(
        "alerts.management.commands.send_unread_reminders.send_telegram_reminder_report",
        fake_send_reminder_report,
    )

    stdout = StringIO()
    call_command(
        "send_unread_reminders",
        "--min-age-minutes=30",
        "--reminder-interval-minutes=60",
        stdout=stdout,
    )

    due.refresh_from_db()
    due_same_case.refresh_from_db()
    assert sent == [[due_same_case.id, due.id]]
    assert due.last_reminded_at is not None
    assert due_same_case.last_reminded_at is not None
    assert "Reminder report sent: 2 alerts." in stdout.getvalue()
    assert "Sent 2, failed 0" in stdout.getvalue()


@pytest.mark.django_db
def test_send_unread_reminders_dry_run_does_not_send(monkeypatch, mailbox):
    sent = []
    due = create_alert(mailbox, minutes_old=45)
    monkeypatch.setattr(
        "alerts.management.commands.send_unread_reminders.send_telegram_reminder_report",
        lambda alerts: sent.append([alert.id for alert in alerts]),
    )

    stdout = StringIO()
    call_command("send_unread_reminders", "--dry-run", stdout=stdout)

    due.refresh_from_db()
    assert sent == []
    assert due.last_reminded_at is None
    assert "Due reminders 1" in stdout.getvalue()


@pytest.mark.django_db
def test_send_unread_reminders_skips_quiet_hours(monkeypatch, mailbox):
    sent = []
    due = create_alert(mailbox, minutes_old=45)
    TelegramSettings.objects.create(
        quiet_hours_enabled=True,
        quiet_hours_start=time(0, 0),
        quiet_hours_end=time(0, 0),
    )
    monkeypatch.setattr(
        "alerts.management.commands.send_unread_reminders.send_telegram_reminder_report",
        lambda alerts: sent.append([alert.id for alert in alerts]),
    )

    stdout = StringIO()
    call_command("send_unread_reminders", stdout=stdout)

    due.refresh_from_db()
    assert sent == []
    assert due.last_reminded_at is None
    assert "quiet-hours skipped 1" in stdout.getvalue()


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_saves_last_reminded_at(monkeypatch, mailbox):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    alert = create_alert(mailbox, minutes_old=45)
    alert._telegram_mailbox_label = "Reminder inbox (reminders@example.local)"
    bot = FakeTelegramBot()

    asyncio.run(async_send_telegram_reminder(alert, chat_id="42", bot=bot))

    alert.refresh_from_db()
    assert bot.calls[0]["chat_id"] == "42"
    assert "Reminder" in bot.calls[0]["text"]
    assert "Reminder inbox (reminders@example.local)" in bot.calls[0]["text"]
    assert bot.calls[0]["reply_markup"] is not None
    assert alert.last_reminded_at is not None
    assert alert.telegram_error == ""


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_report_sends_single_message(monkeypatch, mailbox):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    first = create_alert(mailbox, minutes_old=45)
    second = create_alert(mailbox, minutes_old=55)
    first._telegram_mailbox_label = "Reminder inbox (reminders@example.local)"
    second._telegram_mailbox_label = "Reminder inbox (reminders@example.local)"
    bot = FakeTelegramBot()

    asyncio.run(async_send_telegram_reminder_report([first, second], chat_id="42", bot=bot))

    first.refresh_from_db()
    second.refresh_from_db()
    assert len(bot.calls) == 1
    assert bot.calls[0]["chat_id"] == "42"
    assert "⏰ <b>Argus: unread leads</b>" in bot.calls[0]["text"]
    assert "🆕 <b>Unread:</b> 2" in bot.calls[0]["text"]
    assert "📱 <a" not in bot.calls[0]["text"]
    assert bot.calls[0]["reply_markup"] is not None
    assert first.last_reminded_at is not None
    assert second.last_reminded_at is not None
    assert first.telegram_error == ""
    assert second.telegram_error == ""
