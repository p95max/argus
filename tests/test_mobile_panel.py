import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

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
    assert "Мои" in body
    assert "Спам" in body
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
    assert "Полная информация" in body


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
    assert "Журнал" in body
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
    assert "Почта проверена" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_mobile_panel_shows_gmail_operational_card(client, staff_user, alert):
    alert.mailbox.last_checked_at = timezone.now()
    alert.mailbox.last_success_at = timezone.now()
    alert.mailbox.save(update_fields=["last_checked_at", "last_success_at", "updated_at"])
    client.force_login(staff_user)

    response = client.get(reverse("mobile_dashboard"))
    body = response.content.decode("utf-8")

    assert "Gmail" in body
    assert "Последняя проверка" in body
    assert "Новых сегодня" in body


@pytest.mark.django_db
def test_mobile_panel_cases_tab_shows_listing_analytics(client, staff_user, alert):
    alert.listing_id = "case-1"
    alert.listing_title = "BMW 320d"
    alert.buyer_name = "Max"
    alert.priority = MarketplaceAlert.Priority.HIGH
    alert.save(
        update_fields=[
            "listing_id",
            "listing_title",
            "buyer_name",
            "priority",
            "updated_at",
        ]
    )
    client.force_login(staff_user)

    response = client.get(f"{reverse('mobile_dashboard')}?view=cases")
    body = response.content.decode("utf-8")

    assert "Кейсы по объявлениям" in body
    assert "BMW 320d" in body
    assert "Всего: 1" in body
    assert "High: 1" in body


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
