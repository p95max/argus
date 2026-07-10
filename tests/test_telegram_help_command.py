from pathlib import Path

from alerts.telegram.help_command import ACTIVE_BOT_COMMANDS, build_bot_commands


ROOT = Path(__file__).resolve().parents[1]


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
