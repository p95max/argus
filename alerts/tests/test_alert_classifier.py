"""Tests for marketplace-message classification rules."""

from alerts.classifier import classify_marketplace_message
from alerts.models import MarketplaceAlert


def test_installment_payment_is_risk_flag():
    result = classify_marketplace_message(
        "Hallo, ich bin Alleinverdiener und könnte nur in Raten zahlen. "
        "Ich könnte monatlich 350€ zahlen."
    )

    assert "installment_payment" in result.flag_codes
    assert "рассрочки/оплаты частями" in result.reason


def test_ratenzahlung_is_detected():
    result = classify_marketplace_message("Wäre Ratenzahlung bei Ihnen möglich?")

    assert "installment_payment" in result.flag_codes


def test_normal_cash_question_is_not_installment_flag():
    result = classify_marketplace_message("Ist Barzahlung bei Abholung möglich?")

    assert "installment_payment" not in result.flag_codes


def test_shipping_payment_story_is_marked_for_support_as_scam():
    result = classify_marketplace_message(
        "Leider kann ich nicht persönlich vorbeikommen. Ich halte mich im Ausland auf "
        "und bin bereit, per Überweisung zu zahlen. Die Spedition Eurosender wird den "
        "Auto bei Ihnen abholen. Der Spediteur wird bevollmächtigt sein, den Kaufvertrag "
        "in meinem Namen zu unterzeichnen."
    )

    assert "suspected_scam" in result.flag_codes
    assert result.priority == MarketplaceAlert.Priority.HIGH
    assert "службу поддержки" in result.reason


def test_price_offer_is_detected():
    result = classify_marketplace_message(
        "Würden Sie den Preis von 3.700 Euro akzeptieren?"
    )

    assert "price_negotiation" in result.flag_codes
    assert "торг / предложение цены" in result.reason


def test_phone_number_is_not_detected_as_price_offer():
    result = classify_marketplace_message(
        "Sie können mich unter 0176 12345678 erreichen."
    )

    assert "price_negotiation" not in result.flag_codes


def test_phone_number_near_offer_word_is_not_detected_as_price():
    result = classify_marketplace_message(
        "Mein Angebot: Rufen Sie mich bitte unter 0151 23456789 an."
    )

    assert "price_negotiation" not in result.flag_codes
