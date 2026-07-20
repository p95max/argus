import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from alerts.gmail_polling import GmailPollingStatus
from alerts.models import MailboxAccount, MarketplaceAlert, ServiceEvent, TelegramSettings


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="staff",
        password="pass",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return get_user_model().objects.create_user(
        username="regular",
        password="pass",
    )


@pytest.fixture
def alert(db):
    mailbox = MailboxAccount.objects.create(name="Mobile inbox", email="mobile@example.local")
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        listing_title="Audi A4",
        message_text="Noch da?",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        priority=MarketplaceAlert.Priority.HIGH,
    )


@pytest.mark.django_db
def test_mobile_panel_requires_staff(client, regular_user):
    client.force_login(regular_user)

    response = client.get(reverse("mobile_dashboard"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_mobile_panel_redirects_anonymous_user_to_admin_login(client, settings, alert):
    settings.DJANGO_ADMIN_URL = "control"
    settings.LOGIN_URL = "/control/login/"
    mobile_url = reverse("mobile_alert_detail", args=[alert.id])

    response = client.get(mobile_url)

    assert response.status_code == 302
    assert response["Location"] == f"/control/login/?next={mobile_url}"


@pytest.mark.django_db
def test_mobile_panel_shows_needs_attention_and_empty_state(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.get(reverse("mobile_dashboard"))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Audi A4" in body
    assert "Today" in body
    assert "Mine" in body
    assert "Ignored" in body
    assert "Archive" in body
    assert "Spam" in body
    assert "Working hours" in body
    assert "Needs attention" in body
    assert "Mobile inbox" in body


@pytest.mark.django_db
def test_mobile_panel_can_take_alert_in_work(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_update_alert_status", args=[alert.id]),
        {"status": MarketplaceAlert.AlertStatus.IN_WORK},
    )

    assert response.status_code == 302
    alert.refresh_from_db()
    assert alert.alert_status == MarketplaceAlert.AlertStatus.IN_WORK
    assert alert.taken_by == staff_user
    assert alert.taken_by_label == "staff"
    assert alert.taken_at is not None


@pytest.mark.django_db
def test_mobile_panel_can_archive_in_work_alert(client, staff_user, alert):
    alert.alert_status = MarketplaceAlert.AlertStatus.IN_WORK
    alert.taken_by = staff_user
    alert.taken_by_label = "staff"
    alert.taken_at = timezone.now()
    alert.save(
        update_fields=[
            "alert_status",
            "taken_by",
            "taken_by_label",
            "taken_at",
            "updated_at",
        ]
    )
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_update_alert_status", args=[alert.id]),
        {
            "status": MarketplaceAlert.AlertStatus.ARCHIVED,
            "next": f"{reverse('mobile_dashboard')}?view=mine",
        },
    )

    assert response.status_code == 302
    alert.refresh_from_db()
    assert alert.alert_status == MarketplaceAlert.AlertStatus.ARCHIVED
    assert alert.taken_by is None
    assert alert.taken_by_label == ""
    assert alert.taken_at is None


@pytest.mark.django_db
def test_mobile_alert_detail_links_to_full_admin(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.get(reverse("mobile_alert_detail", args=[alert.id]))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Lead" in body
    assert "Audi A4" in body
    assert reverse("admin:alerts_marketplacealert_change", args=[alert.id]) in body
    assert "Full information" in body


@pytest.mark.django_db
def test_mobile_panel_shows_system_events_tab(client, staff_user, alert):
    ServiceEvent.objects.create(
        mailbox=alert.mailbox,
        alert=alert,
        event_type=ServiceEvent.EventType.TELEGRAM_SEND_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        status=ServiceEvent.Status.OPEN,
        source="telegram",
        title="Telegram send failed",
        details="Bot token is not configured.",
        fingerprint="telegram-send-failed-mobile-test",
    )
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=system")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "System log" in body
    assert "Telegram send failed" in body
    assert "Bot token is not configured." in body
    assert "mobile@example.local" in body
    assert f"/m/alerts/{alert.id}/" in body


@pytest.mark.django_db
def test_mobile_panel_system_events_empty_state(client, staff_user):
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=system")

    assert response.status_code == 200
    assert "There are no system messages or errors yet." in response.content.decode("utf-8")


@pytest.mark.django_db
def test_mobile_panel_today_tab(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=today")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Today" in body
    assert "Audi A4" in body


@pytest.mark.django_db
def test_mobile_panel_my_in_work_tab(client, staff_user, alert):
    alert.alert_status = MarketplaceAlert.AlertStatus.IN_WORK
    alert.taken_by = staff_user
    alert.taken_by_label = "staff"
    alert.save(update_fields=["alert_status", "taken_by", "taken_by_label", "updated_at"])
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=mine")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "My in-work leads" in body
    assert "Case resolved" in body
    assert "✅ Take to work" not in body
    assert "Audi A4" in body


@pytest.mark.django_db
def test_mobile_panel_ignored_tab(client, staff_user, alert):
    alert.alert_status = MarketplaceAlert.AlertStatus.IGNORED
    alert.listing_title = "Ignored Audi A4"
    alert.save(update_fields=["alert_status", "listing_title", "updated_at"])
    MarketplaceAlert.objects.create(
        mailbox=alert.mailbox,
        listing_title="Visible BMW",
        message_text="Noch da?",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
    )
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=ignored")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Ignored leads" in body
    assert "Ignored Audi A4" in body
    assert "Visible BMW" not in body
    assert "Listing cases" not in body


@pytest.mark.django_db
def test_mobile_panel_archived_tab(client, staff_user, alert):
    alert.alert_status = MarketplaceAlert.AlertStatus.ARCHIVED
    alert.listing_title = "Archived Audi A4"
    alert.priority = MarketplaceAlert.Priority.URGENT
    alert.save(update_fields=["alert_status", "listing_title", "priority", "updated_at"])
    MarketplaceAlert.objects.create(
        mailbox=alert.mailbox,
        listing_title="Visible BMW",
        message_text="Noch da?",
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
    )
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=archived")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Archive" in body
    assert "Archived Audi A4" in body
    assert "Visible BMW" not in body

    attention_response = client.get(f"{reverse('mobile_dashboard')}?view=attention")
    attention_body = attention_response.content.decode("utf-8")
    assert "Archived Audi A4" not in attention_body


@pytest.mark.django_db
def test_mobile_panel_noise_tab(client, staff_user, alert):
    alert.event_type = MarketplaceAlert.EventType.NOISE
    alert.listing_title = ""
    alert.subject = "Kleinanzeigen Newsletter"
    alert.save(update_fields=["event_type", "listing_title", "subject", "updated_at"])
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=noise")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Spam and newsletters" in body
    assert "Kleinanzeigen Newsletter" in body


@pytest.mark.django_db
def test_mobile_panel_toggles_quiet_hours(client, staff_user):
    settings = TelegramSettings.load()
    assert settings.quiet_hours_enabled is False
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_toggle_quiet_hours"),
        {"next": reverse("mobile_dashboard")},
    )

    assert response.status_code == 302
    settings.refresh_from_db()
    assert settings.quiet_hours_enabled is True


@pytest.mark.django_db
def test_mobile_panel_manual_mailbox_check(monkeypatch, client, staff_user, alert):
    staff_user.is_superuser = True
    staff_user.save(update_fields=["is_superuser"])
    checked = []

    class Result:
        fetched = 2
        created = 1
        duplicates = 1

    def fake_check_mailbox(mailbox):
        checked.append(mailbox.id)
        return Result()

    monkeypatch.setattr("alerts.mobile.check_mailbox", fake_check_mailbox)
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_check_mailbox_now", args=[alert.mailbox_id]),
        {"next": f"{reverse('mobile_dashboard')}?view=system"},
        follow=True,
    )

    assert response.status_code == 200
    assert checked == [alert.mailbox_id]
    assert "Mail checked" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_mobile_panel_shows_gmail_operational_card(client, staff_user, alert):
    alert.mailbox.last_checked_at = timezone.now()
    alert.mailbox.last_success_at = timezone.now()
    alert.mailbox.save(update_fields=["last_checked_at", "last_success_at", "updated_at"])
    client.force_login(staff_user)

    response = client.get(reverse("mobile_dashboard"))
    body = response.content.decode("utf-8")

    assert "Gmail" in body
    assert "Last check" in body
    assert "New today" in body


@pytest.mark.django_db
def test_mobile_panel_shows_gmail_polling_block(monkeypatch, client, staff_user, alert):
    staff_user.is_superuser = True
    staff_user.save(update_fields=["is_superuser"])
    monkeypatch.setattr(
        "alerts.mobile.get_gmail_polling_status",
        lambda: GmailPollingStatus(
            enabled_state="enabled",
            active_state="active",
            next_run_label="14:20",
            interval_label="15 minutes",
        ),
    )
    client.force_login(staff_user)

    response = client.get(reverse("mobile_dashboard"))
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Gmail polling" in body
    assert "14:20" in body
    assert reverse("mobile_gmail_polling_action", args=["disable"]) in body
    assert reverse("mobile_gmail_polling_action", args=["run_now"]) in body


@pytest.mark.django_db
def test_mobile_panel_can_mark_service_event_recovered(client, staff_user, alert):
    event = ServiceEvent.objects.create(
        mailbox=alert.mailbox,
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        status=ServiceEvent.Status.OPEN,
        source="test",
        title="Mailbox error",
        details="boom",
        fingerprint="mobile-recover-test",
    )
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_service_event_action", args=[event.id]),
        {"action": "mark_recovered", "next": f"{reverse('mobile_dashboard')}?view=system"},
    )

    assert response.status_code == 302
    event.refresh_from_db()
    assert event.status == ServiceEvent.Status.RECOVERED
    assert event.resolved_at is not None


@pytest.mark.django_db
def test_mobile_panel_rejects_unsafe_next_redirect(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_update_alert_status", args=[alert.id]),
        {
            "status": MarketplaceAlert.AlertStatus.IGNORED,
            "next": "https://evil.example/phish",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("mobile_dashboard")
