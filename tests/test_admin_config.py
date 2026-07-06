import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from alerts.admin import MarketplaceAlertAdmin, NeedsAttentionFilter, NoiseAlertAdmin
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


@pytest.fixture
def staff_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username="operator",
        password="pass",
        is_staff=True,
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


@pytest.mark.django_db
def test_marketplace_alert_admin_needs_attention_filter(mailbox):
    unread = create_alert(mailbox, event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
    ignored = create_alert(mailbox, event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
    ignored.alert_status = MarketplaceAlert.AlertStatus.IGNORED
    ignored.priority = MarketplaceAlert.Priority.LOW
    ignored.save(update_fields=["alert_status", "priority", "updated_at"])

    request = RequestFactory().get(
        "/control/alerts/marketplacealert/",
        {"needs_attention": "yes"},
    )
    filter_instance = NeedsAttentionFilter(
        request,
        request.GET.copy(),
        MarketplaceAlert,
        MarketplaceAlertAdmin(MarketplaceAlert, AdminSite()),
    )

    ids = set(
        filter_instance.queryset(
            request,
            MarketplaceAlert.objects.all(),
        ).values_list("id", flat=True)
    )

    assert ids == {unread.id}


@pytest.mark.django_db
def test_marketplace_alert_admin_mark_in_work_sets_operator(mailbox, staff_user):
    alert = create_alert(mailbox, event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
    request = RequestFactory().post("/control/alerts/marketplacealert/")
    request.user = staff_user
    model_admin = MarketplaceAlertAdmin(MarketplaceAlert, AdminSite())
    model_admin.message_user = lambda *args, **kwargs: None

    model_admin.mark_as_in_work(request, MarketplaceAlert.objects.filter(id=alert.id))

    alert.refresh_from_db()
    assert alert.alert_status == MarketplaceAlert.AlertStatus.IN_WORK
    assert alert.taken_by == staff_user
    assert alert.taken_by_label == "operator"


@pytest.mark.django_db
def test_marketplace_alert_admin_test_telegram_action(monkeypatch, mailbox, staff_user):
    alert = create_alert(mailbox, event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
    sent = []
    monkeypatch.setattr("alerts.admin.send_telegram_alert", lambda alert: sent.append(alert.id))
    request = RequestFactory().post("/control/alerts/marketplacealert/")
    request.user = staff_user
    model_admin = MarketplaceAlertAdmin(MarketplaceAlert, AdminSite())
    model_admin.message_user = lambda *args, **kwargs: None

    model_admin.send_test_telegram_alert(request, MarketplaceAlert.objects.filter(id=alert.id))

    assert sent == [alert.id]
