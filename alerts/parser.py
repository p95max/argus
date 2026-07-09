from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re

from .models import MarketplaceAlert
from .classifier import classify_marketplace_message


class BodyTextExtractor(HTMLParser):
    block_tags = {"br", "div", "p", "li", "tr", "table", "section", "article"}
    ignored_tags = {"head", "style", "script", "title", "meta", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.ignored_tags:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.ignored_tags:
            self.ignored_depth = max(self.ignored_depth - 1, 0)
            return
        if self.ignored_depth:
            return
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.ignored_depth:
            return
        self.parts.append(data)

    def text(self):
        return "".join(self.parts)


@dataclass(frozen=True)
class ParsedMarketplaceEmail:
    event_type: str
    parse_status: str
    parse_error: str = ""
    listing_title: str = ""
    listing_id: str = ""
    buyer_name: str = ""
    message_text: str = ""
    raw_subject: str = ""
    raw_body: str = ""
    normalized_body: str = ""
    subject: str = ""
    priority: str = MarketplaceAlert.Priority.NORMAL
    flag_codes: tuple[str, ...] = ()
    classification_reason: str = ""


BUYER_MESSAGE_PATTERNS = (
    r"\bneue nachricht von\b",
    r"\bhat dir eine nachricht geschrieben\b",
    r"\bvon\s*:\s*.+\bnachricht\s*:",
    r"\breplied to your ad\b",
    r"\bhat auf deine anzeige geantwortet\b",
    r"\bantwortete auf deine anzeige\b",
    r"\bein interessent hat eine anfrage zu ihrer anzeige gesendet\b",
    r"\bein interessent hat eine anfrage zu deiner anzeige gesendet\b",
    r"\bnutzer-anfrage zu deiner anzeige\b",
)
LISTING_OPERATION_PATTERNS = (
    "\\bl(?:\u00e4|ae)uft bald ab\\b",
    "\\banzeige l(?:\u00e4|ae)uft ab\\b",
    r"\blisting expiring\b",
    r"\bdeine anzeige endet\b",
    "\\bdeine anzeige l(?:\u00e4|ae)uft\\b",
)
PROMOTIONAL_NOISE_PATTERNS = (
    r"\bnewsletter\b",
    r"\bangebot(?:e)? der woche\b",
    r"\baktion\b",
    r"\bwerbung\b",
    r"\brabatt\b",
    r"\bgutschein\b",
    r"\bpartnerangebot(?:e)?\b",
    r"\btipps von kleinanzeigen\b",
    r"\bkleinanzeigen magazin\b",
    "\\bempfehlungen f(?:\u00fcr|uer) dich\\b",
    r"\bneue angebote\b",
)
GENERIC_SYSTEM_PATTERNS = (
    r"\bsicher bezahlen\b",
    r"\bkleinanzeigen-konto\b",
    r"\bpasswort\b",
    r"\bsicherheitshinweis\b",
    r"\bdein konto\b",
    "\\banzeige wurde erfolgreich ver(?:\u00f6|oe)ffentlicht\\b",
    "\\berfolgreich ver(?:\u00f6|oe)ffentlicht\\b",
    "\\banzeige gel(?:\u00f6|oe)scht\\b",
)
QUOTED_VALUE = r"[\"„“”‟«]([^\"„“”‟«»\n]{3,120})[\"“”‟»]"
INVISIBLE_CHARS_RE = re.compile("[\u200b\u200c\u200d\ufeff]")


def normalize_body(body: str) -> str:
    text = body or ""
    if re.search(r"<[a-zA-Z][^>]*>", text):
        parser = BodyTextExtractor()
        parser.feed(text)
        text = parser.text()

    text = unescape(text)
    text = INVISIBLE_CHARS_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _strip_signature(text.strip())
    return text.strip()


def parse_kleinanzeigen_email(subject: str, body: str) -> ParsedMarketplaceEmail:
    raw_subject = subject or ""
    raw_body = body or ""
    normalized_body = normalize_body(raw_body)
    combined = f"{raw_subject}\n{normalized_body}".strip()
    combined_lower = _normalize_matching_text(combined).lower()

    if _matches_any(combined_lower, PROMOTIONAL_NOISE_PATTERNS):
        event_type = MarketplaceAlert.EventType.NOISE
    elif _matches_any(combined_lower, LISTING_OPERATION_PATTERNS):
        event_type = MarketplaceAlert.EventType.LISTING_EXPIRING
    elif _matches_any(combined_lower, BUYER_MESSAGE_PATTERNS):
        event_type = MarketplaceAlert.EventType.BUYER_MESSAGE
    elif _matches_any(combined_lower, GENERIC_SYSTEM_PATTERNS):
        event_type = MarketplaceAlert.EventType.SYSTEM_NOTICE
    else:
        event_type = MarketplaceAlert.EventType.SYSTEM_NOTICE

    listing_title = _parse_listing_title(raw_subject, normalized_body)
    if event_type == MarketplaceAlert.EventType.BUYER_MESSAGE and not listing_title:
        listing_title = _parse_listing_title_from_subject(raw_subject)
    listing_id = _parse_listing_id(combined)
    buyer_name = ""
    message_text = ""
    if event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        buyer_name = _parse_buyer_name(raw_subject, normalized_body)
        message_text = _parse_message_text(combined)
    elif event_type != MarketplaceAlert.EventType.NOISE:
        message_text = _parse_operational_message(normalized_body)

    missing = []
    if event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        if not listing_title:
            missing.append("listing_title")
        if not listing_id:
            missing.append("listing_id")
        if not buyer_name:
            missing.append("buyer_name")
        if not message_text:
            missing.append("message_text")

    parse_status = MarketplaceAlert.ParseStatus.SUCCESS
    parse_error = ""
    if event_type == MarketplaceAlert.EventType.NOISE:
        parse_status = MarketplaceAlert.ParseStatus.SKIPPED
    elif missing:
        parse_status = MarketplaceAlert.ParseStatus.PARTIAL
        parse_error = "Missing fields: " + ", ".join(missing)

    priority = MarketplaceAlert.Priority.NORMAL
    flag_codes = ()
    classification_reason = "Operational/system event; buyer lead classifier was not applied."
    if event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        # Classify only the buyer-authored message, not subject/listing metadata.
        # Otherwise listing titles like "... TÜV bis ..." create false risk flags.
        classification = classify_marketplace_message(message_text)
        priority = classification.priority
        flag_codes = classification.flag_codes
        classification_reason = classification.reason
    if event_type == MarketplaceAlert.EventType.NOISE:
        priority = MarketplaceAlert.Priority.LOW
        classification_reason = "Promotional/system noise; skipped as buyer lead."

    return ParsedMarketplaceEmail(
        event_type=event_type,
        parse_status=parse_status,
        parse_error=parse_error,
        listing_title=listing_title,
        listing_id=listing_id,
        buyer_name=buyer_name,
        message_text=message_text,
        raw_subject=raw_subject,
        raw_body=raw_body,
        normalized_body=normalized_body,
        subject=raw_subject.strip(),
        priority=priority,
        flag_codes=flag_codes,
        classification_reason=classification_reason,
    )


def _strip_signature(text: str) -> str:
    signature_patterns = (
        r"\n--\s*\n.*$",
        r"\nViele Grüße[\s\S]*$",
        r"\nMit freundlichen Grüßen[\s\S]*$",
        r"\nDein Kleinanzeigen-Team[\s\S]*$",
        r"\nDiese Nachricht wurde.*$",
    )
    stripped = text
    for pattern in signature_patterns:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
    return stripped


def _normalize_matching_text(text: str) -> str:
    replacements = {
        "Ã¤": "ä",
        "Ã¶": "ö",
        "Ã¼": "ü",
        "Ã„": "Ä",
        "Ã–": "Ö",
        "Ãœ": "Ü",
        "ÃŸ": "ß",
        "ÃƒÂ¤": "ä",
        "ÃƒÂ¶": "ö",
        "ÃƒÂ¼": "ü",
    }
    normalized = INVISIBLE_CHARS_RE.sub("", text or "")
    for broken, fixed in replacements.items():
        normalized = normalized.replace(broken, fixed)
    return normalized


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.S) for pattern in patterns)


def _parse_listing_title(subject: str, body: str) -> str:
    candidates = (
        rf"Anzeige\s+{QUOTED_VALUE}\s+erfolgreich ver(?:ö|oe)ffentlicht",
        rf"Anzeige\s+gel(?:ö|oe)scht\s*:\s*{QUOTED_VALUE}",
        rf"die Anzeige\s+{QUOTED_VALUE}",
        rf"zu\s+Anzeige\s+{QUOTED_VALUE}",
        r'(?:Anzeige|Artikel|Inserat|Angebot)\s*[:"]\s*"?([^"\n]+)"?',
        rf"zu deiner Anzeige\s+{QUOTED_VALUE}",
        rf"zu\s+{QUOTED_VALUE}",
        rf"für\s+{QUOTED_VALUE}",
        QUOTED_VALUE,
    )
    text = f"{subject}\n{body}"
    for pattern in candidates:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_value(match.group(1))
    return ""


def _parse_listing_title_from_subject(subject: str) -> str:
    value = _clean_value(subject)
    if not value or len(value) > 140:
        return ""

    normalized = _normalize_matching_text(value).lower()
    notification_patterns = (
        BUYER_MESSAGE_PATTERNS
        + LISTING_OPERATION_PATTERNS
        + PROMOTIONAL_NOISE_PATTERNS
        + GENERIC_SYSTEM_PATTERNS
    )
    if _matches_any(normalized, notification_patterns):
        return ""

    if normalized in {"nunito sans", "kleinanzeigen"}:
        return ""

    return value


def _parse_listing_id(text: str) -> str:
    patterns = (
        r"(?:Anzeigen-ID|Anzeige-ID|Anzeigennummer|listing[_\s-]?id|ad[_\s-]?id)\s*[:#]?\s*([A-Za-z0-9-]{5,})",
        r"/s-anzeige/[^/\s]+/([0-9]{5,})-[0-9-]+",
        r"\byour ad\s+([0-9]{5,})",
        r"\banfrage zu (?:ihrer|deiner) anzeige gesendet\s*:\s*([0-9]{5,})",
        r"\bID\s*[:#]\s*([A-Za-z0-9-]{5,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_value(match.group(1))
    return ""


def _parse_buyer_name(subject: str, body: str) -> str:
    text = f"{subject}\n{body}"
    patterns = (
        r"Neue Nachricht von\s+(.+?)(?:\s+zu|\n|$)",
        r"(.+?)\s+hat dir eine Nachricht geschrieben",
        r"^(.+?)\s+über\s+Kleinanzeigen\s+replied to your ad\b",
        r"^(.+?)\s+via\s+Kleinanzeigen\s+replied to your ad\b",
        r"Von\s*:\s*(.+)",
        r"Absender\s*:\s*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.M)
        if match:
            return _clean_value(match.group(1))
    if re.search(r"\bein interessent hat eine anfrage zu", text, flags=re.IGNORECASE):
        return "Interessent"
    if re.search(r"\bnutzer-anfrage zu deiner anzeige\b", text, flags=re.IGNORECASE):
        return "Interessent"
    return ""


def _parse_message_text(body: str) -> str:
    patterns = (
        r"Nachricht\s*:\s*(.+?)(?:\n\n|Anzeigen-ID|Anzeige-ID|Antworten|$)",
        r"Message\s*:\s*(.+?)(?:\n\n|Listing ID|Antworten|$)",
        r"schreibt\s*:\s*(.+?)(?:\n\n|Anzeigen-ID|Anzeige-ID|Antworten|$)",
        r"replied to your ad\s+[0-9]{5,}\s*:\s*(.+?)(?:\n\n|Anzeigen-ID|Anzeige-ID|Antworten|$)",
        r"anfrage zu (?:ihrer|deiner) anzeige gesendet\s*:\s*[0-9]{5,}\s*:\s*(.+?)(?:\n\n|Anzeigen-ID|Anzeige-ID|Antworten|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.IGNORECASE | re.S)
        if match:
            return _clean_value(match.group(1))

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    ignored_prefixes = (
        "neue nachricht",
        "anzeigen-id",
        "anzeige:",
        "von:",
        "antworten",
        "hallo",
        "kleinanzeigen |",
        "span.",
    )
    message_lines = [
        line for line in lines if not line.lower().startswith(ignored_prefixes)
    ]
    return _clean_value("\n".join(message_lines[:4]))


def _parse_operational_message(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    ignored_prefixes = (
        "anzeigen-id",
        "anzeige-id",
        "id:",
        "hallo",
        "kleinanzeigen |",
        "span.",
    )
    message_lines = [
        line for line in lines if not line.lower().startswith(ignored_prefixes)
    ]
    return _clean_value("\n".join(message_lines[:4]))


def _clean_value(value: str) -> str:
    value = INVISIBLE_CHARS_RE.sub("", unescape(value or ""))
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\n\r\"'„“”‟«»")
