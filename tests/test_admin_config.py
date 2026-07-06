import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from alerts.admin import MarketplaceAlertAdmin, NoiseAlertAdmin
from alerts.apps import AlertsConfig
from alerts.models import (
    LeadFlag,
    MailboxAccount,
    MarketplaceAlert,
    NoiseAlert,
    ProcessedEmail,
    ServiceEvent,
    TelegramSettings,
)


def test_marketplace_alert_admin_has_event_type_filter():
    assert "event_type" in MarketplaceAlertAdmin.list_filter


def test_admin_section_names_are_human_friendly():
    assert AlertsConfig.verbose_name == "Почта и обращения"
    assert MailboxAccount._meta.verbose_name_plural == "Почтовые ящики"
    assert MarketplaceAlert._meta.verbose_name_plural == "Обращения"
    assert NoiseAlert._meta.verbose_name_plural == "Спам и рассылки"
    assert ProcessedEmail._meta.verbose_name_plural == "Проверенные письма"
    assert LeadFlag._meta.verbose_name_plural == "Приоритеты обращений"
    assert ServiceEvent._meta.verbose_name_plural == "Системный журнал"
    assert TelegramSettings._meta.verbose_name_plural == "Настройки Telegram"


@pytest.fixture
def admin_request():
    return RequestFactory().get("/control/alerts/noisealert/")


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(name="Admin test", email="admin-test@example.local")


def create_alert(mailbox, *, event_type):
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        event_type=event_type,
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        priority=MarketplaceAlert.Priority.LOW,
        parse_status=MarketplaceAlert.ParseStatus.SKIPPED,
        subject="Kleinanzeigen Newsletter",
    )


@pytest.mark.django_db
def test_noise_alert_admin_queryset_only_shows_noise(admin_request, mailbox):
    noise = create_alert(mailbox, event_type=MarketplaceAlert.EventType.NOISE)
    create_alert(mailbox, event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
    model_admin = NoiseAlertAdmin(NoiseAlert, AdminSite())

    ids = set(model_admin.get_queryset(admin_request).values_list("id", flat=True))

    assert ids == {noise.id}


@pytest.mark.django_db
def test_noise_alert_admin_can_promote_useful_noise_to_buyer_message(admin_request, mailbox):
    noise = create_alert(mailbox, event_type=MarketplaceAlert.EventType.NOISE)
    model_admin = NoiseAlertAdmin(NoiseAlert, AdminSite())
    model_admin.message_user = lambda *args, **kwargs: None

    model_admin.mark_as_buyer_message(
        admin_request,
        NoiseAlert.objects.filter(id=noise.id),
    )

    noise.refresh_from_db()
    assert noise.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert noise.parse_status == MarketplaceAlert.ParseStatus.PARTIAL
    assert noise.alert_status == MarketplaceAlert.AlertStatus.UNREAD
