import re

from django import template


register = template.Library()


BOILERPLATE_MARKERS = (
    "Beantworte diese Nachricht",
    "Schütze dich vor Betrug",
    "Dein Team von Kleinanzeigen",
    "Allgemeine Nutzungsbedingungen",
    "Datenschutzerklärung",
    "Impressum",
)


@register.filter
def compact_buyer_message(value: str) -> str:
    """Return only the buyer-authored part of a Kleinanzeigen email."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    patterns = (
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
