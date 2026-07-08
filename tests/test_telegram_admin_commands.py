import asyncio
from types import SimpleNamespace

from alerts.telegram.handlers import (
    build_bot_help_message,
    build_manual_deploy_message,
    handle_deploy_command,
    handle_help_command,
)


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class FakeUpdate:
    def __init__(self, chat_id="42", user_id="100"):
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser(user_id)
        self.effective_message = FakeMessage()


class FakeCompletedProcess:
    returncode = 0
    stdout = "deploy <ok> & done\n"


class FakeContext:
    application = SimpleNamespace(bot_data={})


def test_build_bot_help_message_contains_admin_commands():
    message = build_bot_help_message()

    assert "/health" in message
    assert "/status" in message
    assert "/summary" in message
    assert "/doctor" in message
    assert "/deploy" in message
    assert "/help" in message


def test_build_manual_deploy_message_runs_configured_command(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return FakeCompletedProcess()

    monkeypatch.setenv("TELEGRAM_MANUAL_DEPLOY_COMMAND", "/usr/local/bin/argus-deploy.sh --manual")
    monkeypatch.setenv("TELEGRAM_MANUAL_DEPLOY_TIMEOUT_SECONDS", "17")
    monkeypatch.setattr("alerts.telegram.handlers.subprocess.run", fake_run)

    message = build_manual_deploy_message()

    assert calls[0][0] == ["/usr/local/bin/argus-deploy.sh", "--manual"]
    assert calls[0][1]["timeout"] == 17
    assert "✅ <b>Argus deploy finished</b>" in message
    assert "deploy &lt;ok&gt; &amp; done" in message


def test_build_manual_deploy_message_reports_failed_command(monkeypatch):
    class FailedCompletedProcess:
        returncode = 1
        stdout = "boom"

    monkeypatch.setenv("TELEGRAM_MANUAL_DEPLOY_COMMAND", "/usr/local/bin/argus-deploy.sh")
    monkeypatch.setattr(
        "alerts.telegram.handlers.subprocess.run",
        lambda *args, **kwargs: FailedCompletedProcess(),
    )

    message = build_manual_deploy_message()

    assert "🚨 <b>Argus deploy finished</b>" in message
    assert "boom" in message


def test_handle_deploy_command_rejects_allowed_non_default_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "99")
    monkeypatch.setattr(
        "alerts.telegram.handlers.build_manual_deploy_message",
        lambda: (_ for _ in ()).throw(AssertionError("deploy must not run")),
    )
    update = FakeUpdate(chat_id="99")

    asyncio.run(handle_deploy_command(update, FakeContext()))

    assert len(update.effective_message.replies) == 1
    assert "только в TELEGRAM_DEFAULT_CHAT_ID" in update.effective_message.replies[0][0]


def test_handle_deploy_command_runs_only_in_default_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.setattr(
        "alerts.telegram.handlers.build_manual_deploy_message",
        lambda: "✅ <b>deploy ok</b>",
    )
    update = FakeUpdate(chat_id="42")

    asyncio.run(handle_deploy_command(update, FakeContext()))

    assert len(update.effective_message.replies) == 2
    assert "Запускаю ручной деплой" in update.effective_message.replies[0][0]
    assert update.effective_message.replies[1][0] == "✅ <b>deploy ok</b>"
    assert update.effective_message.replies[1][1]["parse_mode"] == "HTML"


def test_handle_help_command_rejects_allowed_non_default_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "99")
    update = FakeUpdate(chat_id="99")

    asyncio.run(handle_help_command(update, FakeContext()))

    assert len(update.effective_message.replies) == 1
    assert "Подсказка команд доступна только" in update.effective_message.replies[0][0]


def test_handle_help_command_answers_in_default_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    update = FakeUpdate(chat_id="42")

    asyncio.run(handle_help_command(update, FakeContext()))

    assert len(update.effective_message.replies) == 1
    assert "/deploy" in update.effective_message.replies[0][0]
    assert update.effective_message.replies[0][1]["parse_mode"] == "HTML"
