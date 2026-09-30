from types import SimpleNamespace

import pytest
from django.urls import reverse

from alerts.management.commands.check_gmail import _gmail_polling_skip_reason
from alerts.models import GmailPollingSettings, MailboxAccount


@pytest.mark.django_db
def test_dashboard_pause_and_resume_are_post_only_and_persist_state(
    client,
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_superuser(
        username="pause-admin",
        email="pause@example.local",
        password="pass",
    )
    client.force_login(user)
    polling = GmailPollingSettings.load()

    sent = []
    monkeypatch.setattr(
        "alerts.telegram.sender.send_system_telegram_alert",
        lambda title, details="": sent.append((title, details)),
    )

    url = reverse("mobile_toggle_gmail_polling")

    assert client.get(url).status_code == 405

    response = client.post(
        url,
        {"action": "pause", "next": reverse("mobile_dashboard")},
    )
    assert response.status_code == 302
    polling.refresh_from_db()
    assert polling.polling_enabled is False
    assert polling.paused_at is not None
    assert polling.paused_by_id == user.id
    assert sent[-1][0] == "Gmail polling paused"

    response = client.post(
        url,
        {"action": "resume", "next": reverse("mobile_dashboard")},
    )
    assert response.status_code == 302
    polling.refresh_from_db()
    assert polling.polling_enabled is True
    assert polling.paused_at is None
    assert polling.paused_by_id is None
    assert sent[-1][0] == "Gmail polling resumed"


@pytest.mark.django_db
def test_scheduled_check_skips_while_paused_but_force_bypasses_pause():
    mailbox = MailboxAccount.objects.create(
        name="Paused mailbox",
        email="paused@example.local",
        is_active=True,
    )
    polling = GmailPollingSettings.load()
    polling.polling_enabled = False
    polling.save(update_fields=["polling_enabled", "updated_at"])

    reason = _gmail_polling_skip_reason([mailbox], force=False)
    assert "paused" in reason.lower()

    assert _gmail_polling_skip_reason([mailbox], force=True) == ""


@pytest.mark.django_db
def test_manual_mobile_gmail_check_still_works_while_polling_is_paused(
    client,
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_superuser(
        username="manual-admin",
        email="manual@example.local",
        password="pass",
    )
    client.force_login(user)

    MailboxAccount.objects.create(
        name="Manual mailbox",
        email="manual-mailbox@example.local",
        is_active=True,
    )
    polling = GmailPollingSettings.load()
    polling.polling_enabled = False
    polling.save(update_fields=["polling_enabled", "updated_at"])

    monkeypatch.setattr(
        "alerts.views.mobile.dashboard.check_mailbox",
        lambda mailbox: SimpleNamespace(fetched=1, created=0, duplicates=0),
    )
    monkeypatch.setattr(
        "alerts.views.mobile.dashboard.refresh_listing_view_stats",
        lambda force=False: (0, 0),
    )

    response = client.post(
        reverse("mobile_check_gmail_now"),
        {"next": reverse("mobile_dashboard")},
    )

    assert response.status_code == 302
