import pytest

from alerts.backup_status import BackupJob, BackupJobStatus, BackupStatus
from alerts.models import MailboxAccount, MarketplaceAlert
from alerts.server_timers import ServerTimer, ServerTimerStatus, ServerTimersStatus
from alerts.telegram.messages import build_health_message


@pytest.fixture
def alert(db):
    mailbox = MailboxAccount.objects.create(
        name="Health Telegram",
        email="health-telegram@example.local",
        is_active=True,
    )
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        subject="Health alert",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
    )


@pytest.mark.django_db
def test_build_health_message_contains_operational_state(monkeypatch, alert):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")
    backup = BackupJob("local", "local.timer", "local.service")
    monkeypatch.setattr(
        "alerts.health.get_backup_status",
        lambda: BackupStatus(
            (BackupJobStatus(backup, "enabled", "active", "success", "2026-07-23 02:30"),)
        ),
    )
    timer = ServerTimer("gmail", "argus-check-gmail.timer")
    monkeypatch.setattr(
        "alerts.health.get_server_timers_status",
        lambda: ServerTimersStatus(
            (ServerTimerStatus(timer, "enabled", "active", "12:45:00"),)
        ),
    )
    alert.mailbox.last_checked_at = alert.created_at
    alert.mailbox.last_success_at = alert.created_at
    alert.mailbox.save(update_fields=["last_checked_at", "last_success_at", "updated_at"])

    message = build_health_message(bot_started_at=alert.created_at)

    assert "🩺 <b>Argus: health</b>" in message
    assert "🟢 <b>DB:</b> OK" in message
    assert "🟢 <b>Gmail:</b> OK" in message
    assert (
        "💾 <b>Backups:</b>\n"
        "   Local archive: success (timer: active, Last run: 2026-07-23 02:30)"
    ) in message
    assert "⏱ <b>Server timers:</b>\n   🟢 Gmail checks: active, next run: 12:45:00" in message
    assert "🟢 <b>Mailboxes:</b> active 1 / errors 0" in message
    assert "🔴 <b>Open errors:</b> 0" in message
    assert "🆕 <b>New leads:</b> 1" in message
    assert "🤖 <b>Bot uptime:</b>" in message
    assert 'href="http://127.0.0.1:8000/m/"' in message
    assert "Open mobile admin" in message
