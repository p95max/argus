import pytest

from alerts.classifier import classify_marketplace_message
from alerts.models import LeadFlag, MailboxAccount, MarketplaceAlert
from alerts.parser import parse_kleinanzeigen_email
from alerts.seed_data import DEMO_MAILBOX_EMAIL, STARTER_LEAD_FLAGS, seed_demo_alerts, seed_lead_flags


def test_inspection_message_gets_high_priority():
    result = parse_kleinanzeigen_email(
        'Neue Nachricht von Max zu "BMW 320d Touring"',
        "Von: Max\nNachricht: Ich kann heute zur Besichtigung kommen.\nAnzeigen-ID: 123456789",
    )

    assert result.priority == MarketplaceAlert.Priority.HIGH
    assert "inspection_request" in result.flag_codes
    assert "today" in result.flag_codes
    assert "осмотру" in result.classification_reason


def test_courier_shipping_message_gets_risk_flag():
    classification = classify_marketplace_message(
        "Ich schicke einen Kurier zur Abholung und zahle per Überweisung vorab."
    )

    assert classification.priority == MarketplaceAlert.Priority.NORMAL
    assert "courier_shipping" in classification.flag_codes
    assert "risky_payment" in classification.flag_codes
    assert "risk flags" in classification.reason


def test_weak_last_price_message_is_low_priority():
    classification = classify_marketplace_message("Was letzter Preis???")

    assert classification.priority == MarketplaceAlert.Priority.LOW
    assert classification.flag_codes == ("last_price", "odd_style")


@pytest.mark.django_db
def test_seed_lead_flags_is_idempotent():
    created, updated = seed_lead_flags()
    assert created == len(STARTER_LEAD_FLAGS)
    assert updated == 0

    created_again, updated_again = seed_lead_flags()
    assert created_again == 0
    assert updated_again == len(STARTER_LEAD_FLAGS)
    assert LeadFlag.objects.count() == len(STARTER_LEAD_FLAGS)


@pytest.mark.django_db
def test_seed_demo_alerts_is_idempotent(settings):
    settings.DEBUG = True
    seed_lead_flags()

    created, updated = seed_demo_alerts()
    assert created == 3
    assert updated == 0

    created_again, updated_again = seed_demo_alerts()
    assert created_again == 0
    assert updated_again == 3
    assert MailboxAccount.objects.filter(email=DEMO_MAILBOX_EMAIL).exists()
    assert MarketplaceAlert.objects.filter(mailbox__email=DEMO_MAILBOX_EMAIL).count() == 3


@pytest.mark.django_db
def test_seed_demo_alerts_is_local_only(settings):
    settings.DEBUG = False

    with pytest.raises(RuntimeError, match="DEBUG=True"):
        seed_demo_alerts()
