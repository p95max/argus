from io import StringIO

import pytest
from django.core.management import call_command

from alerts.monitoring.health import build_health_report


@pytest.mark.django_db
def test_full_health_is_ok_without_mailboxes(monkeypatch):
    monkeypatch.setattr(
        "alerts.monitoring.health.get_backup_status",
        lambda: type(
            "BackupStatusStub",
            (),
            {"is_available": False, "is_healthy": True, "jobs": ()},
        )(),
    )
    monkeypatch.setattr(
        "alerts.monitoring.health.get_server_timers_status",
        lambda: type(
            "ServerTimersStatusStub",
            (),
            {"is_available": False, "is_healthy": True, "timers": (), "error": ""},
        )(),
    )
    monkeypatch.setattr(
        "alerts.monitoring.health.get_telegram_config",
        lambda: type(
            "TelegramConfigStub",
            (),
            {
                "bot_token": "token",
                "allowed_chat_ids": {"1"},
            },
        )(),
    )

    report = build_health_report()

    assert report["ok"] is True
    assert report["checks"]["active_mailbox"]["ok"] is True
    assert report["checks"]["active_mailbox"]["status"] == "idle"
    assert report["checks"]["gmail_recent_check"]["ok"] is True
    assert report["checks"]["gmail_recent_check"]["status"] == "idle"


@pytest.mark.django_db
def test_check_gmail_command_exits_successfully_without_mailboxes(monkeypatch):
    monkeypatch.setattr(
        "alerts.management.commands.check_gmail.refresh_listing_view_stats",
        lambda: (0, 0),
    )
    stdout = StringIO()

    call_command("check_gmail", stdout=stdout)

    assert "no active mailboxes configured" in stdout.getvalue().lower()
