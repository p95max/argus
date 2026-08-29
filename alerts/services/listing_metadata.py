"""Public Kleinanzeigen listing metadata used by Telegram analytics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from .kleinanzeigen import (
    KleinanzeigenTemporaryError,
    _NoRedirectHandler,
    _fetch_payload,
    build_opener,
    validate_kleinanzeigen_url,
)


@dataclass(frozen=True)
class ListingPublicMetadata:
    published_on: date | None


def parse_listing_publication_date(page_html: str, *, today: date | None = None) -> date | None:
    """Extract the public publication date from known Kleinanzeigen page variants."""

    text = page_html or ""
    today = today or timezone.localdate()

    iso_patterns = (
        r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})',
        r'itemprop=["\']datePosted["\'][^>]+(?:content|datetime)=["\'](\d{4}-\d{2}-\d{2})',
        r'(?:content|datetime)=["\'](\d{4}-\d{2}-\d{2})[^>]+itemprop=["\']datePosted["\']',
    )
    for pattern in iso_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return date.fromisoformat(match.group(1))
            except ValueError:
                pass

    label_pattern = re.compile(
        r"(?:Erstellungsdatum|Eingestellt(?:\s+am)?|Online\s+seit|Veröffentlicht(?:\s+am)?)"
        r".{0,180}?(Heute|Gestern|\d{1,2}\.\d{1,2}\.\d{4})",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = label_pattern.search(text)
    if not match:
        return None

    value = match.group(1).strip()
    if value.casefold() == "heute":
        return today
    if value.casefold() == "gestern":
        return today - timedelta(days=1)

    try:
        day, month, year = (int(part) for part in value.split("."))
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def fetch_listing_public_metadata(url: str, *, opener=None) -> ListingPublicMetadata:
    """Fetch the validated public listing page and return non-sensitive metadata."""

    validated = validate_kleinanzeigen_url(url)
    opener = opener or build_opener(_NoRedirectHandler())
    try:
        payload = _fetch_payload(validated.normalized_url, opener=opener)
    except Exception as exc:
        raise KleinanzeigenTemporaryError("listing_unavailable") from exc

    page_html = payload.decode("utf-8", errors="replace")
    return ListingPublicMetadata(
        published_on=parse_listing_publication_date(page_html),
    )
