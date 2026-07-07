from io import StringIO
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from alerts.health import build_health_report
from alerts.models import MailboxAccount


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
