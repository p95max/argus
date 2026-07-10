import asyncio

import pytest

from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.telegram.sender import (
    async_send_telegram_alert,
    async_send_telegram_reminder_report,
    send_system_telegram_message,
)

from alerts.telegram.messages import (
    build_alert_message,
    build_system_message,
    build_mailbox_status_message,
    build_daily_summary_message,
)

from alerts.telegram.handlers import (
    ACTIVE_BOT_COMMANDS,
    build_help_message,
    build_unread_command_message,
    handle_alert_callback_action,
    update_alert_status_from_callback,
)

from alerts.telegram.keyboards import (
    build_alert_keyboard,
)


class FakeTelegramMessage:
    message_id = 987


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
    )


@pytest.mark.django_db
def test_build_alert_message_contains_main_details(alert):
    message = build_alert_message(alert)

    assert "<b>Новое обращение</b>" in message
    assert "Ящик" in message
    assert "Inbox (inbox@example.local)" in message
    assert "Max" in message
    assert "BMW 320d Touring" in message
    assert "Ich kann heute" in message


@pytest.mark.django_db
def test_build_alert_message_keeps_operational_event_separate_from_buyer_lead(alert):
    alert.event_type = MarketplaceAlert.EventType.LISTING_EXPIRING
    alert.buyer_name = "Max"
    alert.message_text = "Deine Anzeige läuft bald ab."
    alert.save(update_fields=["event_type", "buyer_name", "message_text", "updated_at"])

    message = build_alert_message(alert)

    assert "Kleinanzeigen" in message
    assert "BMW 320d Touring" in message
    assert "Deine Anzeige" in message
    assert "Max" not in message


def test_build_system_message_escapes_html():
    message = build_system_message("Gmail error", "<bad>")

    assert "Argus: системное уведомление" in message
    assert "&lt;bad&gt;" in message


def test_build_help_message_lists_active_bot_commands():
    message = build_help_message()

    assert "🤖 <b>Argus: что умеет бот</b>" in message
    assert "мобильную админку" in message
    for command, description in ACTIVE_BOT_COMMANDS:
        assert f"/{command} — {description}" in message
    assert "Open Mobile" in message


@pytest.mark.django_db
def test_update_alert_status_from_allowed_callback(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    updated = update_alert_status_from_callback(f"alert:{alert.id}:in_work", chat_id="42", user_id="100")

    assert updated.alert_status == MarketplaceAlert.AlertStatus.IN_WORK
    assert updated.taken_by_label == "Telegram user 100"
    assert updated.taken_at is not None


@pytest.mark.django_db
def test_update_alert_status_rejects_unknown_chat(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(PermissionError):
        update_alert_status_from_callback(f"alert:{alert.id}:ignored", chat_id="99")


@pytest.mark.django_db
def test_update_alert_status_accepts_allowed_user(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "100")

    updated = update_alert_status_from_callback(
        f"alert:{alert.id}:in_work",
        chat_id="42",
        user_id="100",
    )

    assert updated.alert_status == MarketplaceAlert.AlertStatus.IN_WORK


@pytest.mark.django_db
def test_update_alert_status_rejects_unknown_user(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "100")

    with pytest.raises(PermissionError):
        update_alert_status_from_callback(
            f"alert:{alert.id}:ignored",
            chat_id="42",
            user_id="999",
        )


@pytest.mark.django_db
def test_status_callback_does_not_change_alert_status(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    alert.alert_status = MarketplaceAlert.AlertStatus.UNREAD
    alert.save(update_fields=["alert_status", "updated_at"])

    result = handle_alert_callback_action(
        f"alert:{alert.id}:status",
        chat_id="42",
    )

    alert.refresh_from_db()

    assert alert.alert_status == MarketplaceAlert.AlertStatus.UNREAD
    assert result.status_changed is False
    assert "New" in result.answer_text


@pytest.mark.django_db
def test_build_alert_message_contains_status(alert):
    alert.taken_by_label = "Telegram user 100"
    alert.classification_reason = "Есть признаки срочного покупателя."
    alert.save(update_fields=["taken_by_label", "classification_reason", "updated_at"])

    message = build_alert_message(alert)

    assert "Статус" in message
    assert alert.get_alert_status_display() in message
    assert "Telegram user 100" in message
    assert "Есть признаки" in message


@pytest.mark.django_db
def test_alert_keyboard_contains_open_mobile_link(settings, alert):
    settings.ARGUS_PUBLIC_BASE_URL = "http://localhost:8000"

    keyboard = build_alert_keyboard(alert)

    assert keyboard.inline_keyboard[-1][0].text == "Open Mobile"
    url = keyboard.inline_keyboard[-1][0].url
    assert url == f"http://localhost:8000/m/alerts/{alert.id}/"


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_alert_saves_telegram_delivery(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)

    bot = FakeTelegramBot()

    asyncio.run(
        async_send_telegram_alert(
            alert,
            chat_id="42",
            bot=bot,
        )
    )

    alert.refresh_from_db()

    assert bot.calls[0]["chat_id"] == "42"
    assert bot.calls[0]["reply_markup"] is not None
    assert alert.telegram_chat_id == "42"
    assert alert.telegram_message_id == "987"
    assert alert.telegram_sent_at is not None
    assert alert.telegram_error == ""


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_alert_saves_error(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)

    with pytest.raises(RuntimeError, match="telegram is down"):
        asyncio.run(
            async_send_telegram_alert(
                alert,
                chat_id="42",
                bot=BrokenTelegramBot(),
            )
        )

    alert.refresh_from_db()

    assert alert.telegram_error == "telegram is down"


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_alert_rejects_disallowed_chat(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(PermissionError, match="Telegram chat is not allowed"):
        asyncio.run(
            async_send_telegram_alert(
                alert,
                chat_id="99",
                bot=FakeTelegramBot(),
            )
        )

    alert.refresh_from_db()
    assert alert.telegram_sent_at is None
    assert alert.telegram_error == ""


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_report_saves_error_for_all_alerts(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    second = MarketplaceAlert.objects.create(
        mailbox=alert.mailbox,
        buyer_name="Anna",
        listing_title="VW Golf",
        message_text="Noch da?",
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
    )

    with pytest.raises(RuntimeError, match="telegram is down"):
        asyncio.run(
            async_send_telegram_reminder_report(
                [alert, second],
                chat_id="42",
                bot=BrokenTelegramBot(),
            )
        )

    alert.refresh_from_db()
    second.refresh_from_db()
    assert alert.telegram_error == "telegram is down"
    assert second.telegram_error == "telegram is down"
    assert alert.last_reminded_at is None
    assert second.last_reminded_at is None


@pytest.mark.django_db(transaction=True)
def test_async_send_telegram_reminder_report_rejects_disallowed_chat(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(PermissionError, match="Telegram chat is not allowed"):
        asyncio.run(
            async_send_telegram_reminder_report(
                [alert],
                chat_id="99",
                bot=FakeTelegramBot(),
            )
        )

    alert.refresh_from_db()
    assert alert.last_reminded_at is None
    assert alert.telegram_error == ""


def test_send_system_telegram_message_requires_bot_token_when_bot_is_not_injected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        asyncio.run(send_system_telegram_message("Deploy failed"))


def test_send_system_telegram_message_sends_html(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    bot = FakeTelegramBot()

    message = asyncio.run(
        send_system_telegram_message(
            "Health",
            details="<bad>",
            chat_id="42",
            bot=bot,
        )
    )

    assert message.message_id == 987
    assert bot.calls[0]["chat_id"] == "42"
    assert bot.calls[0]["parse_mode"] == "HTML"
    assert bot.calls[0]["disable_web_page_preview"] is True
    assert "⚙️ <b>Argus: системное уведомление</b>" in bot.calls[0]["text"]
    assert "📌 Health" in bot.calls[0]["text"]
    assert "🧾 &lt;bad&gt;" in bot.calls[0]["text"]


@pytest.mark.django_db
def test_build_mailbox_status_message_contains_mailbox_health(alert):
    mailbox = alert.mailbox
    mailbox.last_error = "old gmail error"
    mailbox.save(update_fields=["last_error", "updated_at"])

    message = build_mailbox_status_message()

    assert "Argus: статус ящиков" in message
    assert mailbox.email in message
    assert "Последняя проверка" in message
    assert "Последний успех" in message
    assert "old gmail error" in message
    assert "новые" in message
    assert "в работе" in message


@pytest.mark.django_db
def test_build_daily_summary_message_contains_today_counters(alert):
    message = build_daily_summary_message()

    assert "Argus: дневная сводка" in message
    assert "Всего событий сегодня" in message
    assert "Сообщения покупателей" in message
    assert "Новые" in message
    assert "В работе" in message
    assert "Активные ящики" in message


@pytest.mark.django_db
def test_build_unread_command_message_reports_unread_without_marking_reminded(alert):
    second = MarketplaceAlert.objects.create(
        mailbox=alert.mailbox,
        buyer_name="Anna",
        listing_id="unread-command-case-2",
        listing_title="VW Golf",
        message_text="Noch da?",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        priority=MarketplaceAlert.Priority.NORMAL,
    )
    MarketplaceAlert.objects.create(
        mailbox=alert.mailbox,
        listing_title="Noise",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        event_type=MarketplaceAlert.EventType.NOISE,
    )

    message = build_unread_command_message()

    alert.refresh_from_db()
    second.refresh_from_db()
    assert "⏰ <b>Argus: непрочитанные обращения</b>" in message
    assert "🆕 <b>Непрочитано:</b> 2" in message
    assert "BMW 320d Touring" in message
    assert "VW Golf" in message
    assert "Noise" not in message
    assert alert.last_reminded_at is None
    assert second.last_reminded_at is None
