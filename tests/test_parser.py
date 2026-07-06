import pytest

from alerts.models import MarketplaceAlert
from alerts.parser import normalize_body, parse_kleinanzeigen_email


def test_parse_buyer_message():
    result = parse_kleinanzeigen_email(
        'Neue Nachricht von Max zu "BMW 320d Touring"',
        """
        Hallo,

        Von: Max
        Nachricht: Ist das Auto noch verfügbar? Ich kann heute zur Besichtigung kommen.

        Anzeigen-ID: 123456789
        """,
    )

    assert result.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.buyer_name == "Max"
    assert result.listing_title == "BMW 320d Touring"
    assert result.listing_id == "123456789"
    assert "Besichtigung" in result.message_text
    assert result.priority == MarketplaceAlert.Priority.HIGH
    assert "inspection_request" in result.flag_codes


def test_parse_listing_expiring_system_notice():
    result = parse_kleinanzeigen_email(
        'Deine Anzeige "VW Golf GTI" läuft bald ab',
        "Deine Anzeige läuft bald ab.\nAnzeigen-ID: 987654321",
    )

    assert result.event_type == MarketplaceAlert.EventType.LISTING_EXPIRING
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.listing_title == "VW Golf GTI"
    assert result.listing_id == "987654321"
    assert result.buyer_name == ""
    assert "buyer lead classifier was not applied" in result.classification_reason


def test_listing_expiration_with_real_umlaut_is_operational_event():
    result = parse_kleinanzeigen_email(
        'Deine Anzeige "Audi A6 Avant" läuft bald ab',
        "Deine Anzeige läuft bald ab.\nAnzeigen-ID: 111222333",
    )

    assert result.event_type == MarketplaceAlert.EventType.LISTING_EXPIRING
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.listing_title == "Audi A6 Avant"
    assert result.listing_id == "111222333"
    assert result.buyer_name == ""


def test_missing_listing_id_is_partial_not_error():
    result = parse_kleinanzeigen_email(
        'Neue Nachricht von Anna zu "Audi A4 Avant"',
        "Von: Anna\nNachricht: Können wir morgen telefonieren?",
    )

    assert result.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert result.parse_status == MarketplaceAlert.ParseStatus.PARTIAL
    assert "listing_id" in result.parse_error
    assert result.buyer_name == "Anna"


def test_html_body_is_normalized_and_parsed():
    body = """
    <html><body>
      <p>Von: Julia</p>
      <p>Nachricht: Hallo &amp; guten Tag, ist der TÜV neu?</p>
      <p>Anzeigen-ID: 555777999</p>
    </body></html>
    """

    result = parse_kleinanzeigen_email('Neue Nachricht von Julia zu "Mercedes C 200"', body)

    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert "Hallo & guten Tag" in result.message_text
    assert "<p>" not in result.normalized_body
    assert result.listing_id == "555777999"


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Kleinanzeigen Newsletter", "Angebot der Woche und neue Tipps von Kleinanzeigen"),
        ("Rabatt Aktion", "Newsletter: spare heute bei Partnerangeboten"),
    ],
)
def test_noise_email(subject, body):
    result = parse_kleinanzeigen_email(subject, body)

    assert result.event_type == MarketplaceAlert.EventType.NOISE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SKIPPED
    assert result.priority == MarketplaceAlert.Priority.LOW
    assert result.buyer_name == ""
    assert result.message_text == ""


def test_promotional_newsletter_is_not_buyer_message_even_with_message_word():
    result = parse_kleinanzeigen_email(
        "Neue Nachrichten und Angebote von Kleinanzeigen",
        "Newsletter: neue Angebote, Rabatt und Tipps von Kleinanzeigen.",
    )

    assert result.event_type == MarketplaceAlert.EventType.NOISE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SKIPPED
    assert result.buyer_name == ""
    assert result.listing_id == ""


def test_generic_kleinanzeigen_system_notice_is_not_buyer_message():
    result = parse_kleinanzeigen_email(
        "Sicherheitshinweis zu deinem Kleinanzeigen-Konto",
        "Bitte prüfe dein Konto. Das ist keine Nachricht von einem Käufer.",
    )

    assert result.event_type == MarketplaceAlert.EventType.SYSTEM_NOTICE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.buyer_name == ""


def test_normalize_body_removes_signature_noise():
    normalized = normalize_body("Hallo   Welt<br><br>Viele Grüße\nMax")

    assert normalized == "Hallo Welt"
