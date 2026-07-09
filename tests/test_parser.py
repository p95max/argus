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


def test_parse_english_kleinanzeigen_buyer_reply_from_screenshot_format():
    result = parse_kleinanzeigen_email(
        "AUDI A3 1.6 MPI TÜV bis 03/27",
        """
        <html>
            <head>
                <title>Nunito Sans</title>
                <style>
                    span.MsoHyperlink { mso-style-priority: 1; color: inherit; }
                </style>
            </head>
            <body>
                <div>Kleinanzeigen | Anzeigen gratis inserieren mit Kleinanzeigen</div>
                <p>Thomas über Kleinanzeigen replied to your ad 3394403772: Hätte heute Abend ab 20:00 Uhr Zeit. Wie sieht es bei Ihnen aus?</p>
            </body>
        </html>
        """,
    )

    assert result.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.buyer_name == "Thomas"
    assert result.listing_title == "AUDI A3 1.6 MPI TÜV bis 03/27"
    assert result.listing_id == "3394403772"
    assert result.message_text == "Hätte heute Abend ab 20:00 Uhr Zeit. Wie sieht es bei Ihnen aus?"
    assert "buyer lead classifier was not applied" not in result.classification_reason
    assert "Nunito Sans" not in result.normalized_body
    assert "span.MsoHyperlink" not in result.normalized_body


def test_buyer_classifier_ignores_listing_title_tuv_false_positive():
    result = parse_kleinanzeigen_email(
        "AUDI A3 1.6 MPI TÜV bis 03/27",
        "Thomas über Kleinanzeigen replied to your ad 3394403772:\n\nDann hätten sie das besser kommunizieren müssen",
    )

    assert result.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.buyer_name == "Thomas"
    assert result.listing_title == "AUDI A3 1.6 MPI TÜV bis 03/27"
    assert result.listing_id == "3394403772"
    assert result.message_text == "Dann hätten sie das besser kommunizieren müssen"
    assert result.priority == MarketplaceAlert.Priority.NORMAL
    assert result.flag_codes == ()


def test_buyer_classifier_still_uses_buyer_message_text_for_tuv_question():
    result = parse_kleinanzeigen_email(
        "AUDI A3 1.6 MPI",
        "Thomas über Kleinanzeigen replied to your ad 3394403772: Ist der TÜV neu?",
    )

    assert result.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.message_text == "Ist der TÜV neu?"
    assert result.priority == MarketplaceAlert.Priority.NORMAL
    assert "tuv_question" in result.flag_codes


def test_parse_german_interested_buyer_request_from_real_mailbox_format():
    result = parse_kleinanzeigen_email(
        "AUDI A3 1.6 MPI TÜV bis 03/27",
        "Ein Interessent hat eine Anfrage zu Ihrer Anzeige gesendet: 3394403772: Guten Tag, ist das Fahrzeug noch zu haben?",
    )

    assert result.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE
    assert result.parse_status == MarketplaceAlert.ParseStatus.SUCCESS
    assert result.buyer_name == "Interessent"
    assert result.listing_title == "AUDI A3 1.6 MPI TÜV bis 03/27"
    assert result.listing_id == "3394403772"
    assert result.message_text == "Guten Tag, ist das Fahrzeug noch zu haben?"
    assert "buyer lead classifier was not applied" not in result.classification_reason


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
    assert "tuv_question" in result.flag_codes
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


def test_normalize_body_ignores_html_head_style_and_title():
    normalized = normalize_body(
        """
        <html>
            <head>
                <title>Nunito Sans</title>
                <style>span.MsoHyperlink { color: inherit; }</style>
            </head>
            <body><p>Hallo Welt</p></body>
        </html>
        """
    )

    assert normalized == "Hallo Welt"
