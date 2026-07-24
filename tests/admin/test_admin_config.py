import pytest
from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.urls import reverse
from django.utils import translation

from alerts.admin import (
    ArgusSettingsAdmin,
    MailboxAccountAdmin,
    MarketplaceAlertAdmin,
    NeedsAttentionFilter,
    NoiseAlertAdmin,
)
from alerts.apps import AlertsConfig
from alerts.models import (
    AdminLoginLog,
    ArgusSettings,
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
    with translation.override("en"):
        assert AlertsConfig.verbose_name == "Mail and leads"
        assert MailboxAccount._meta.verbose_name_plural == "Mailboxes"
        assert MarketplaceAlert._meta.verbose_name_plural == "Leads"
        assert NoiseAlert._meta.verbose_name_plural == "Spam and newsletters"
        assert ProcessedEmail._meta.verbose_name_plural == "Processed emails"
        assert LeadFlag._meta.verbose_name_plural == "Lead priority rules"
        assert ServiceEvent._meta.verbose_name_plural == "System log"
        assert AdminLoginLog._meta.verbose_name_plural == "Access logs"
        assert TelegramSettings._meta.verbose_name_plural == "Telegram settings"


def test_admin_section_names_translate_to_russian():
    with translation.override("ru"):
        assert MailboxAccount._meta.verbose_name_plural == "Почтовые ящики"
        assert MarketplaceAlert._meta.verbose_name_plural == "Обращения"
        assert NoiseAlert._meta.verbose_name_plural == "Спам и рассылки"
        assert ProcessedEmail._meta.verbose_name_plural == "Проверенные письма"
        assert LeadFlag._meta.verbose_name_plural == "Приоритеты обращений"
        assert ServiceEvent._meta.verbose_name_plural == "Системный журнал"
        assert TelegramSettings._meta.verbose_name_plural == "Настройки Telegram"


@pytest.mark.django_db
def test_mailbox_admin_add_form_hides_email_until_oauth(django_user_model):
    model_admin = MailboxAccountAdmin(MailboxAccount, AdminSite())
    request = RequestFactory().get("/control/alerts/mailboxaccount/add/")
    request.user = django_user_model.objects.create_superuser(
        username="mailbox-admin",
        email="mailbox-admin@example.local",
        password="pass",
    )

    add_fields = {
        field
        for _, fieldset_options in model_admin.get_fieldsets(request, obj=None)
        for field in fieldset_options["fields"]
    }

    assert "email" not in add_fields
    assert "email_display" in model_admin.get_readonly_fields(request)


def test_mailbox_admin_email_display_explains_missing_oauth():
    model_admin = MailboxAccountAdmin(MailboxAccount, AdminSite())
    mailbox = MailboxAccount(name="Test")

    with translation.override("en"):
        assert (
            model_admin.email_display(mailbox)
            == "Email is not connected yet. Connect Gmail through OAuth."
        )


def test_argus_settings_admin_language_field_is_radio_choice():
    model_admin = ArgusSettingsAdmin(ArgusSettings, AdminSite())
    request = RequestFactory().get("/control/alerts/argussettings/1/change/")

    form = model_admin.get_form(request)()

    assert form.fields["language_code"].widget.__class__.__name__ == "RadioSelect"
    assert "Django Admin" in form.fields["language_code"].help_text


@pytest.mark.django_db
def test_argus_settings_changelist_redirects_to_singleton_change(client):
    user = get_user_model().objects.create_superuser(
        username="root",
        email="root@example.local",
        password="pass",
    )
    settings = ArgusSettings.load()
    client.force_login(user)

    response = client.get(reverse("admin:alerts_argussettings_changelist"))

    assert response.status_code == 302
    assert response["Location"] == reverse(
        "admin:alerts_argussettings_change",
        args=[settings.id],
    )


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
