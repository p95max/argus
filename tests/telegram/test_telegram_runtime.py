import asyncio
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from telegram.ext import CallbackQueryHandler

from alerts.telegram.handlers import (
    handle_help_command,
    handle_gmail_polling_command,
    handle_mailbox_status_command,
)


class FakeTelegramMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeTelegramUpdate:
    def __init__(self, chat_id="42", user_id="100"):
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": user_id})()
        self.effective_message = FakeTelegramMessage()


class FakeApplication:
    def __init__(self):
        self.bot_data = {}
        self.handlers = []
        self.error_handlers = []
        self.run_polling_kwargs = None

    def add_error_handler(self, handler):
        self.error_handlers.append(handler)

    def add_handler(self, handler):
        self.handlers.append(handler)

    def run_polling(self, **kwargs):
        self.run_polling_kwargs = kwargs


class FakeApplicationBuilder:
    def __init__(self, app):
        self.app = app
        self.token_value = ""
        self.post_init_callback = None

    def token(self, value):
        self.token_value = value
        return self

    def post_init(self, callback):
        self.post_init_callback = callback
        return self

    def build(self):
        return self.app


def test_run_telegram_bot_registers_handlers_and_polling_options(monkeypatch):
    app = FakeApplication()
    builder = FakeApplicationBuilder(app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "100")
    monkeypatch.delenv("TELEGRAM_DEFAULT_CHAT_ID", raising=False)
    monkeypatch.setattr(
        "alerts.management.commands.run_telegram_bot.ApplicationBuilder",
        lambda: builder,
    )
    stdout = StringIO()

    call_command("run_telegram_bot", stdout=stdout)

    command_sets = [
        handler.commands
        for handler in app.handlers
        if hasattr(handler, "commands")
    ]
    assert builder.token_value == "token"
    assert builder.post_init_callback is not None
    assert app.bot_data["argus_started_at"] is not None
    assert len(app.error_handlers) == 1
    assert any(isinstance(handler, CallbackQueryHandler) for handler in app.handlers)
    assert frozenset({"help"}) in command_sets
    assert frozenset({"status", "mailboxes"}) in command_sets
    assert frozenset({"summary"}) in command_sets
    assert frozenset({"health"}) in command_sets
    assert frozenset({"doctor"}) in command_sets
    assert frozenset({"unread"}) in command_sets
    assert frozenset({"polling"}) in command_sets
    assert app.run_polling_kwargs == {
        "allowed_updates": ["callback_query", "message"],
        "drop_pending_updates": True,
    }
    assert "Allowed chats: 42" in stdout.getvalue()
    assert "Allowed users: 100" in stdout.getvalue()


def test_run_telegram_bot_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")

    with pytest.raises(CommandError, match="TELEGRAM_BOT_TOKEN"):
        call_command("run_telegram_bot")


def test_run_telegram_bot_requires_allowed_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_DEFAULT_CHAT_ID", raising=False)

    with pytest.raises(CommandError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        call_command("run_telegram_bot")


def test_help_command_rejects_unknown_chat(monkeypatch):
    update = FakeTelegramUpdate(chat_id="99", user_id="100")
    monkeypatch.setattr("alerts.telegram.handlers.is_allowed_update", lambda update: False)

    asyncio.run(handle_help_command(update, context=object()))

    assert len(update.effective_message.replies) == 1
    assert "does not have access" in update.effective_message.replies[0]["text"]


@pytest.mark.django_db
def test_status_command_replies_with_html_for_allowed_chat(monkeypatch):
    update = FakeTelegramUpdate(chat_id="42", user_id="100")
    monkeypatch.setattr("alerts.telegram.handlers.is_allowed_update", lambda update: True)
    monkeypatch.setattr(
        "alerts.telegram.handlers.build_mailbox_status_message",
        lambda: "<b>Status OK</b>",
    )

    asyncio.run(handle_mailbox_status_command(update, context=object()))

    assert update.effective_message.replies == [
        {
            "text": "<b>Status OK</b>",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ]


def test_gmail_polling_command_replies_with_status_and_buttons(monkeypatch):
    update = FakeTelegramUpdate(chat_id="42", user_id="100")
    monkeypatch.setattr("alerts.telegram.handlers.is_allowed_update", lambda update: True)

    class Status:
        is_enabled = True

    monkeypatch.setattr(
        "alerts.telegram.handlers.get_gmail_polling_status",
        lambda: Status(),
    )
    monkeypatch.setattr(
        "alerts.telegram.handlers.build_gmail_polling_message",
        lambda status: "<b>Polling</b>",
    )

    asyncio.run(handle_gmail_polling_command(update, context=object()))

    reply = update.effective_message.replies[0]
    assert reply["text"] == "<b>Polling</b>"
    assert reply["parse_mode"] == "HTML"
    assert reply["reply_markup"].inline_keyboard[0][0].callback_data == "polling:disable"
