import re

from django import template
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe


register = template.Library()


BOILERPLATE_MARKERS = (
    "Beantworte diese Nachricht",
    "Schütze dich vor Betrug",
    "Dein Team von Kleinanzeigen",
    "Allgemeine Nutzungsbedingungen",
    "Datenschutzerklärung",
    "Impressum",
)

SECURITY_NOTICE_MARKERS = (
    "kontakt mit verdächtigem konto",
    "kontakt mit verdaechtigem konto",
    "zugang von",
    "nutzerkonto eingeschränkt",
    "nutzerkonto eingeschraenkt",
    "verdächtiges konto",
    "verdaechtiges konto",
)


@register.filter
def compact_buyer_message(value: str) -> str:
    """Return only the buyer-authored part of a Kleinanzeigen email."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    patterns = (
        r"Ein\s+Interessent\s+hat\s+eine\s+Anfrage\s+zu\s+deiner\s+Anzeige\s+.*?\(Anzeigennummer:\s*\d+\)\s+gesendet\.\s*(.*?)(?=\s+Beantworte diese Nachricht|\s+Schütze dich vor Betrug|\s+Dein Team von Kleinanzeigen|$)",
        r"Antwort von\s+[^\s:]+\s+(.*?)(?=\s+Beantworte diese Nachricht|\s+Schütze dich vor Betrug|\s+Dein Team von Kleinanzeigen|$)",
        r"Nachricht von\s+[^\s:]+\s+(.*?)(?=\s+Beantworte diese Nachricht|\s+Schütze dich vor Betrug|\s+Dein Team von Kleinanzeigen|$)",
        r"(?:Nachricht|Message)\s*:\s*(.*?)(?=\s+Beantworte diese Nachricht|\s+Antworten\b|\s+Schütze dich vor Betrug|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.S)
        if match:
            candidate = match.group(1).strip(" -:·")
            if candidate:
                return candidate

    for marker in BOILERPLATE_MARKERS:
        position = text.lower().find(marker.lower())
        if position != -1:
            text = text[:position].strip()

    return text.strip(" -:·")


@register.filter
def is_security_system_notice(alert) -> bool:
    """Detect high-value Kleinanzeigen account-security notices without changing event routing."""
    if getattr(alert, "event_type", "") != "system_notice":
        return False

    text = " ".join(
        str(value or "")
        for value in (
            getattr(alert, "subject", ""),
            getattr(alert, "message_text", ""),
            getattr(alert, "normalized_body", ""),
        )
    ).casefold()

    has_security_marker = any(marker in text for marker in SECURITY_NOTICE_MARKERS)
    has_restriction_context = (
        ("eingeschränkt" in text or "eingeschraenkt" in text)
        and ("konto" in text or "zugang" in text)
    )
    return has_security_marker or has_restriction_context


@register.filter(needs_autoescape=True)
def highlight_risk_flags(value: str, autoescape=True):
    """Highlight risk-flag sentences without making stored classifier text HTML-aware."""
    text = str(value or "")
    if not text:
        return ""

    escape = conditional_escape if autoescape else lambda item: item
    pattern = re.compile(
        r"(?P<prefix>(?:Есть\s+)?risk flags?:|Найден(?:ы)?\s+risk flag:)\s*(?P<body>[^.]+\.)",
        flags=re.IGNORECASE,
    )

    parts = []
    position = 0
    for match in pattern.finditer(text):
        parts.append(str(escape(text[position:match.start()])))
        risk_text = f"🚩 {match.group(0)}"
        parts.append(str(format_html('<span class="risk-flag-text">{}</span>', risk_text)))
        position = match.end()

    parts.append(str(escape(text[position:])))
    return mark_safe("".join(parts))
