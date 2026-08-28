"""Regression tests for direct/plain Kleinanzeigen buyer replies."""

from alerts.models import MarketplaceAlert
from alerts.parser import parse_kleinanzeigen_email


def test_plain_direct_reply_is_buyer_message_and_scam_flagged():
    subject = "Skoda Octavia 1.4 tsi 122 ps, tüv neu"
    body = (
        "In welchem Zustand befindet sich der Auto und wie lautet der Endpreis?<br />"
        "Leider kann ich nicht persönlich vorbeikommen, um den Auto abzuholen und<br />"
        "bar zu bezahlen, da ich mich für eine Operation wegen eines Hörproblems im<br />"
        "Ausland aufhalte. Das wird einige Monate dauern. Da ich weiß, dass Sie<br />"
        "nicht so lange warten können, bin ich bereit, per Überweisung zu zahlen.<br />"
        "Die Spedition Eurosender wird sich mit Ihnen in Verbindung setzen und den<br />"
        "Auto bei Ihnen abholen – ganz ohne Stress, verstehen Sie?<br />"
        "Der Spediteur von Eurosender wird bevollmächtigt sein, am Tag der Abholung<br />"
        "in meinem Namen den Kaufvertrag zu unterzeichnen.<br /><br />"
        "Mit freundlichen Grüßen<br /><br />Sophie<br /><br />"
        "On Thu, 27 Aug 2026, 17:15 Privat über Kleinanzeigen, "
        "<abc123@mail.kleinanzeigen.de>"
    )

    parsed = parse_kleinanzeigen_email(subject, body)

    assert parsed.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert parsed.listing_title == subject
    assert parsed.buyer_name == "Sophie"
    assert "Spedition Eurosender" in parsed.message_text
    assert "On Thu" not in parsed.message_text
    assert "suspected_scam" in parsed.flag_codes
    assert parsed.priority == MarketplaceAlert.Priority.HIGH
