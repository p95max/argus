from io import StringIO
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from alerts.backup_status import BackupJob, BackupJobStatus, BackupStatus
from alerts.health import build_health_report
from alerts.models import ArgusSettings, LanguageCode, MailboxAccount
from alerts.seed_data import DEMO_MAILBOX_EMAIL
from alerts.server_timers import ServerTimer, ServerTimerStatus, ServerTimersStatus


@pytest.fixture
def healthy_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")


@pytest.mark.django_db
def test_full_health_requires_staff_or_token(client):
    response = client.get(reverse("health_full"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_full_health_reports_operational_checks(client, django_user_model, healthy_env):
    MailboxAccount.objects.create(
        name="Health",
        email="health@example.local",
        is_active=True,
        last_checked_at=timezone.now(),
        last_success_at=timezone.now(),
    )
    user = django_user_model.objects.create_user(
        username="staff",
        password="pass",
        is_staff=True,
    )
    client.force_login(user)

    response = client.get(reverse("health_full"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"]["ok"] is True
    assert payload["checks"]["active_mailbox"]["ok"] is True


@pytest.mark.django_db
def test_health_report_marks_stale_gmail_check(healthy_env):
    MailboxAccount.objects.create(
        name="Stale",
        email="stale@example.local",
        is_active=True,
        last_checked_at=timezone.now() - timedelta(hours=1),
    )

    report = build_health_report()

    assert report["checks"]["gmail_recent_check"]["ok"] is False
    assert report["checks"]["gmail_recent_check"]["status"] == "warning"


@pytest.mark.django_db
def test_health_report_includes_successful_backup_status(monkeypatch, healthy_env):
    local = BackupJob("local", "local.timer", "local.service")
    remote = BackupJob("remote", "remote.timer", "remote.service")
    monkeypatch.setattr(
        "alerts.health.get_backup_status",
        lambda: BackupStatus(
            (
                BackupJobStatus(local, "enabled", "active", "success", "2026-07-23 02:30"),
                BackupJobStatus(remote, "enabled", "active", "success", "2026-07-23 03:15"),
            )
        ),
    )

    report = build_health_report()

    assert report["checks"]["backup"] == {
        "ok": True,
        "status": "ok",
        "detail": "🟢 Local archive: success (timer: active, Last run: 2026-07-23 02:30); "
        "🟢 Remote copy: success (timer: active, Last run: 2026-07-23 03:15)",
    }
    assert report["labels"]["checks"]["backup"] == "Backups"


@pytest.mark.django_db
def test_health_report_keeps_local_health_ok_without_systemd(monkeypatch, healthy_env):
    monkeypatch.setattr(
        "alerts.health.get_backup_status",
        lambda: BackupStatus((), error="systemctl is unavailable"),
    )

    report = build_health_report()

    assert report["checks"]["backup"]["ok"] is True
    assert report["checks"]["backup"]["status"] == "unavailable"


@pytest.mark.django_db
def test_health_report_marks_failed_backup_red(monkeypatch, healthy_env):
    backup = BackupJob("local", "local.timer", "local.service")
    monkeypatch.setattr(
        "alerts.health.get_backup_status",
        lambda: BackupStatus(
            (BackupJobStatus(backup, "enabled", "active", "failed", "2026-07-23 02:30"),)
        ),
    )

    report = build_health_report()

    assert report["checks"]["backup"]["ok"] is False
    assert report["checks"]["backup"]["detail"].startswith("🔴 Local archive: failed")


@pytest.mark.django_db
def test_health_report_includes_server_timers(monkeypatch, healthy_env):
    timer = ServerTimer("gmail", "argus-check-gmail.timer")
    monkeypatch.setattr(
        "alerts.health.get_server_timers_status",
        lambda: ServerTimersStatus(
            (ServerTimerStatus(timer, "enabled", "active", "12:45:00"),)
        ),
    )

    report = build_health_report()

    assert report["checks"]["server_timers"] == {
        "ok": True,
        "status": "ok",
        "detail": "🟢 Gmail checks: active, next run: 12:45:00",
    }
    assert report["labels"]["checks"]["server_timers"] == "Server timers"


@pytest.mark.django_db
def test_health_report_marks_unhealthy_timer_red(monkeypatch, healthy_env):
    timer = ServerTimer("gmail", "argus-check-gmail.timer")
    monkeypatch.setattr(
        "alerts.health.get_server_timers_status",
        lambda: ServerTimersStatus(
            (ServerTimerStatus(timer, "disabled", "inactive", "", "timer is disabled"),)
        ),
    )

    report = build_health_report()

    assert report["checks"]["server_timers"]["ok"] is False
    assert report["checks"]["server_timers"]["detail"].startswith("🔴 Gmail checks: inactive")


@pytest.mark.django_db
def test_full_health_uses_selected_russian_language(
    client,
    django_user_model,
    healthy_env,
):
    ArgusSettings.objects.create(language_code=LanguageCode.RUSSIAN)
    MailboxAccount.objects.create(
        name="Ready",
        email="ready-health@example.local",
        is_active=True,
        last_checked_at=timezone.now(),
        last_success_at=timezone.now(),
    )

    user = django_user_model.objects.create_user(
        username="health-staff",
        password="pass",
        is_staff=True,
    )
    client.force_login(user)
    response = client.get(reverse("health_full"))

    assert response.status_code == 200
    report = response.json()
    assert report["labels"]["modal_title"] == "Состояние сервиса Argus"
    assert report["labels"]["checks"]["active_mailbox"] == "Активные почтовые ящики"
    assert report["checks"]["active_mailbox"]["detail"] == "Активных почтовых ящиков: 1."
    assert report["checks"]["telegram"]["detail"].startswith("Разрешённых чатов: ")


@pytest.mark.django_db
def test_argus_check_deploy_command_passes_when_ready(settings, healthy_env):
    settings.DEBUG = False
    settings.DATABASE_URL = "postgres://example"
    settings.GMAIL_OAUTH_TOKEN_FERNET_KEY = "key"
    MailboxAccount.objects.create(
        name="Ready",
        email="ready@example.local",
        is_active=True,
        last_checked_at=timezone.now(),
        last_success_at=timezone.now(),
    )
    stdout = StringIO()

    call_command("argus_check_deploy", stdout=stdout)

    assert "Argus deploy status: ok" in stdout.getvalue()


@pytest.mark.django_db
def test_argus_check_deploy_rejects_demo_mailbox(settings, healthy_env):
    settings.DEBUG = False
    settings.DATABASE_URL = "postgres://example"
    settings.GMAIL_OAUTH_TOKEN_FERNET_KEY = "key"
    MailboxAccount.objects.create(
        name="Demo",
        email=DEMO_MAILBOX_EMAIL,
        is_active=True,
        last_checked_at=timezone.now(),
        last_success_at=timezone.now(),
    )

    report = build_health_report(include_deploy_checks=True)

    assert report["checks"]["demo_data"]["ok"] is False
    assert DEMO_MAILBOX_EMAIL in report["checks"]["demo_data"]["detail"]
