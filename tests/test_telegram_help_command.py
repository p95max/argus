from pathlib import Path
import asyncio

from alerts.telegram.help_command import (
    ACTIVE_BOT_COMMANDS,
    build_bot_commands,
    handle_help_command,
)


ROOT = Path(__file__).resolve().parents[1]


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


def test_help_lists_all_registered_commands():
    command_descriptions = dict(ACTIVE_BOT_COMMANDS)

    assert list(command_descriptions) == [
        "help",
        "status",
        "mailboxes",
        "summary",
        "unread",
        "health",
        "doctor",
        "deploy",
    ]
    assert "queue" in command_descriptions["deploy"]
    assert "start" in command_descriptions["deploy"]
    assert "result" in command_descriptions["deploy"]


def test_bot_command_menu_matches_help_command_list():
    commands = build_bot_commands()

    assert [command.command for command in commands] == [
        command for command, _description in ACTIVE_BOT_COMMANDS
    ]
    deploy = next(command for command in commands if command.command == "deploy")
    assert "queue" in deploy.description
    assert "result" in deploy.description


def test_help_command_rejects_disallowed_update(monkeypatch):
    update = FakeTelegramUpdate(chat_id="99", user_id="100")
    monkeypatch.setattr("alerts.telegram.help_command.is_allowed_update", lambda update: False)

    asyncio.run(handle_help_command(update, context=object()))

    assert update.effective_message.replies == [
        {"text": "This user or chat does not have access to Argus."}
    ]


def test_help_command_replies_with_html_for_allowed_update(monkeypatch):
    update = FakeTelegramUpdate(chat_id="42", user_id="100")
    monkeypatch.setattr("alerts.telegram.help_command.is_allowed_update", lambda update: True)

    asyncio.run(handle_help_command(update, context=object()))

    assert len(update.effective_message.replies) == 1
    reply = update.effective_message.replies[0]
    assert "<b>Argus: what the bot can do</b>" in reply["text"]
    assert reply["parse_mode"] == "HTML"
    assert reply["disable_web_page_preview"] is True


def test_telegram_bot_uses_dedicated_help_handler_and_publishes_menu():
    content = (
        ROOT / "alerts" / "management" / "commands" / "run_telegram_bot.py"
    ).read_text()

    assert (
        "from alerts.telegram.help_command import build_bot_commands, "
        "handle_help_command"
    ) in content
    assert 'CommandHandler(\n                "help",\n                handle_help_command,' in content
    assert ".post_init(configure_bot_commands)" in content
    assert "application.bot.set_my_commands(commands)" in content


def test_readme_documents_queue_and_deploy_results():
    content = (ROOT / "README.md").read_text()

    assert "### Background Job Queue" in content
    assert "### Telegram Bot Commands" in content
    assert "`/deploy`" in content
    assert "`UPDATED`" in content
    assert "`UP TO DATE`" in content
    assert "services were not redeployed" in content
