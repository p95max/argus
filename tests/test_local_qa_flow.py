import asyncio
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from alerts.cleanup import cleanup_old_leads
from alerts.gmail.gmail import GmailMessage, check_mailbox as run_mailbox_check
from alerts.models import MailboxAccount, MarketplaceAlert, ProcessedEmail
from alerts.parser import parse_kleinanzeigen_email
from alerts.telegram.handlers import update_alert_status_from_callback
from alerts.telegram.messages import build_mailbox_status_message
from alerts.telegram.sender import async_send_telegram_alert


class FakeTelegramMessage:
    message_id = 1601


class FakeTelegramBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return FakeTelegramMessage()


SAMPLE_BUYER_MESSAGE = GmailMessage(
    message_id="qa-buyer-1",
    thread_id="qa-thread-buyer",
    subject='Neue Nachricht von Max zu "BMW 320d Touring"',
    body="Von: Max\nNachricht: Ist das Auto noch verfügbar?\nAnzeigen-ID: 160100001",
)
SAMPLE_NEWSLETTER = GmailMessage(
    message_id="qa-noise-1",
    thread_id="qa-thread-noise",
    subject="Kleinanzeigen Newsletter",
    body="Newsletter: neue Angebote, Rabatt und Tipps von Kleinanzeigen.",
)
SAMPLE_LISTING_EXPIRING = GmailMessage(
    message_id="qa-expiring-1",
    thread_id="qa-thread-expiring",
    subject='Deine Anzeige "VW Golf GTI" läuft bald ab',
    body="Deine Anzeige läuft bald ab.\nAnzeigen-ID: 160100002",
)


@pytest.mark.django_db(transaction=True)
@override_settings(DEBUG=True)
def test_local_mvp_flow_end_to_end(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_PASSWORD", "qa-local-password")
    monkeypatch.setenv("DEV_SEED_SAMPLE_DATA", "False")
    monkeypatch.setenv("TELEGRAM_SEND_ON_GMAIL_CHECK", "False")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)

    stdout = StringIO()
    call_command(
        "init_dev",
        "--username",
        "qa_admin",
        "--email",
        "qa-admin@example.local",
        stdout=stdout,
    )
    User = get_user_model()
    admin_user = User.objects.get(username="qa_admin")
    assert admin_user.is_staff is True
    assert admin_user.is_superuser is True
    assert "qa_admin" in stdout.getvalue()

    client = Client()
    assert client.login(username="qa_admin", password="qa-local-password") is True
    admin_response = client.get(reverse("admin:index"))
    assert admin_response.status_code == 200
    assert "Argus" in admin_response.content.decode("utf-8", errors="ignore")

    mailbox_add_response = client.post(
        reverse("admin:alerts_mailboxaccount_add"),
        {
            "name": "QA inbox",
            "is_active": "on",
            "_save": "Save",
        },
        follow=True,
    )
    assert mailbox_add_response.status_code == 200
    mailbox = MailboxAccount.objects.get(name="QA inbox")
    assert mailbox.email is None
    mailbox.email = "qa-inbox@example.local"
    mailbox.gmail_connected_email = mailbox.email
    mailbox.connection_status = MailboxAccount.ConnectionStatus.CONNECTED
    mailbox.save(
        update_fields=[
            "email",
            "gmail_connected_email",
            "connection_status",
            "updated_at",
        ]
    )

    parsed_buyer = parse_kleinanzeigen_email(SAMPLE_BUYER_MESSAGE.subject, SAMPLE_BUYER_MESSAGE.body)
    parsed_newsletter = parse_kleinanzeigen_email(SAMPLE_NEWSLETTER.subject, SAMPLE_NEWSLETTER.body)
    parsed_expiring = parse_kleinanzeigen_email(SAMPLE_LISTING_EXPIRING.subject, SAMPLE_LISTING_EXPIRING.body)
    assert parsed_buyer.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert parsed_newsletter.event_type == MarketplaceAlert.EventType.NOISE
    assert parsed_expiring.event_type == MarketplaceAlert.EventType.LISTING_EXPIRING

    def local_check_mailbox(mailbox, service=None, max_results=25):
        return run_mailbox_check(
            mailbox,
            messages=[SAMPLE_BUYER_MESSAGE, SAMPLE_NEWSLETTER, SAMPLE_LISTING_EXPIRING],
            max_results=max_results,
        )

    monkeypatch.setattr("alerts.management.commands.check_gmail.check_mailbox", local_check_mailbox)
    stdout = StringIO()
    call_command("check_gmail", "--mailbox", mailbox.email, stdout=stdout)

    assert "created 3, duplicates 0" in stdout.getvalue()
    assert MarketplaceAlert.objects.filter(mailbox=mailbox).count() == 3
    assert ProcessedEmail.objects.filter(mailbox=mailbox).count() == 3

    buyer_alert = MarketplaceAlert.objects.get(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )
    noise_alert = MarketplaceAlert.objects.get(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.NOISE,
    )
    expiring_alert = MarketplaceAlert.objects.get(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.LISTING_EXPIRING,
    )
    assert noise_alert.priority == MarketplaceAlert.Priority.LOW
    assert expiring_alert.buyer_name == ""

    bot = FakeTelegramBot()
    buyer_alert._telegram_mailbox_label = "QA inbox (qa-inbox@example.local)"
    buyer_alert._telegram_flag_names = ""
    asyncio.run(async_send_telegram_alert(buyer_alert, chat_id="42", bot=bot))
    buyer_alert.refresh_from_db()
    assert bot.calls[0]["chat_id"] == "42"
    assert buyer_alert.telegram_message_id == "1601"

    updated = update_alert_status_from_callback(f"alert:{buyer_alert.id}:in_work", chat_id="42")
    assert updated.alert_status == MarketplaceAlert.AlertStatus.IN_WORK

    mailbox_status = build_mailbox_status_message()
    assert "qa-inbox@example.local" in mailbox_status
    assert "Alerts" in mailbox_status

    reminder_alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        buyer_name="Anna",
        listing_title="Audi A4",
        message_text="Noch verfügbar?",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        priority=MarketplaceAlert.Priority.HIGH,
    )
    old_at = timezone.now() - timedelta(minutes=45)
    MarketplaceAlert.objects.filter(id=reminder_alert.id).update(created_at=old_at)
    sent_reminders = []

    def fake_send_reminder(alert):
        sent_reminders.append(alert.id)
        alert.last_reminded_at = timezone.now()
        alert.save(update_fields=["last_reminded_at", "updated_at"])

    monkeypatch.setattr(
        "alerts.management.commands.send_unread_reminders.send_telegram_reminder",
        fake_send_reminder,
    )
    stdout = StringIO()
    call_command("send_unread_reminders", "--min-age-minutes=30", stdout=stdout)
    reminder_alert.refresh_from_db()
    assert sent_reminders == [reminder_alert.id]
    assert reminder_alert.last_reminded_at is not None

    cleanup_alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_id="cleanup-qa-1",
        listing_title="Old inactive listing",
        alert_status=MarketplaceAlert.AlertStatus.IGNORED,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        priority=MarketplaceAlert.Priority.NORMAL,
    )
    inactive_at = timezone.now() - timedelta(days=45)
    MarketplaceAlert.objects.filter(id=cleanup_alert.id).update(created_at=inactive_at, updated_at=inactive_at)
    cleanup_result = cleanup_old_leads(older_than_days=30)
    assert cleanup_result.selected_cases == 1
    assert not MarketplaceAlert.objects.filter(id=cleanup_alert.id).exists()
    assert MarketplaceAlert.objects.filter(id=buyer_alert.id).exists()
