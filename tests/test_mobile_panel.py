import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

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
def test_mobile_panel_shows_needs_attention_and_empty_state(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.get(reverse("mobile_dashboard"))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Audi A4" in body
    assert "Сегодня" in body
    assert "Мои в работе" in body
    assert "Спам и рассылки" in body
    assert "Рабочие часы" in body
    assert "Требует внимания" in body
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
def test_mobile_alert_detail_links_to_full_admin(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.get(reverse("mobile_alert_detail", args=[alert.id]))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Обращение" in body
    assert "Audi A4" in body
    assert f"/control/alerts/marketplacealert/{alert.id}/change/" in body
    assert "Полная админка" in body


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
    assert "Системный журнал" in body
    assert "Системные сообщения и ошибки" in body
    assert "Telegram send failed" in body
    assert "Bot token is not configured." in body
    assert "mobile@example.local" in body
    assert f"/m/alerts/{alert.id}/" in body


@pytest.mark.django_db
def test_mobile_panel_system_events_empty_state(client, staff_user):
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=system")

    assert response.status_code == 200
    assert "Системных сообщений и ошибок пока нет." in response.content.decode("utf-8")


@pytest.mark.django_db
def test_mobile_panel_today_tab(client, staff_user, alert):
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=today")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Сегодня" in body
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
    assert "Мои в работе" in body
    assert "Audi A4" in body


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
    assert "Спам и рассылки" in body
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
