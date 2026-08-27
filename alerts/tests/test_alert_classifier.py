"""Tests for marketplace-message classification rules."""

from alerts.classifier import classify_marketplace_message


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
