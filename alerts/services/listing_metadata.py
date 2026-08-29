"""Public Kleinanzeigen listing metadata used by Telegram and mobile analytics."""

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


def _parse_publication_value(value: str, *, today: date) -> date | None:
    value = " ".join((value or "").split()).strip(" ,")
    if not value:
        return None

    lowered = value.casefold()
    if lowered.startswith("heute"):
        return today
    if lowered.startswith("gestern"):
        return today - timedelta(days=1)

    match = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", value)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None

    match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", value)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None

    return None


def parse_listing_publication_date(page_html: str, *, today: date | None = None) -> date | None:
    """Extract the public publication date from known Kleinanzeigen page variants."""

    text = page_html or ""
    today = today or timezone.localdate()

    iso_patterns = (
        r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})',
        r'"dateCreated"\s*:\s*"(\d{4}-\d{2}-\d{2})',
        r'itemprop=["\']datePosted["\'][^>]+(?:content|datetime)=["\'](\d{4}-\d{2}-\d{2})',
        r'(?:content|datetime)=["\'](\d{4}-\d{2}-\d{2})[^>]+itemprop=["\']datePosted["\']',
    )
    for pattern in iso_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = _parse_publication_value(match.group(1), today=today)
            if parsed:
                return parsed

    # Kleinanzeigen renders the publication date and view counter together in
    # #viewad-extra-info. The date often has no textual label, e.g.
    # "Heute, 14:51" or "27.08.2026", so inspect this block before using the
    # looser page-wide fallback.
    extra_info_match = re.search(
        r'<(?P<tag>[a-z0-9]+)\b[^>]*\bid=["\']viewad-extra-info["\'][^>]*>(?P<body>.*?)</(?P=tag)>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if extra_info_match:
        extra_info_text = re.sub(r"<[^>]+>", " ", extra_info_match.group("body"))
        extra_info_text = re.sub(r"&nbsp;|&#160;", " ", extra_info_text, flags=re.IGNORECASE)
        extra_info_text = " ".join(extra_info_text.split())

        relative_match = re.search(r"\b(Heute|Gestern)(?:\s*,?\s*\d{1,2}:\d{2})?\b", extra_info_text, flags=re.IGNORECASE)
        if relative_match:
            parsed = _parse_publication_value(relative_match.group(1), today=today)
            if parsed:
                return parsed

        absolute_match = re.search(r"(?<!\d)\d{1,2}\.\d{1,2}\.\d{4}(?!\d)", extra_info_text)
        if absolute_match:
            parsed = _parse_publication_value(absolute_match.group(0), today=today)
            if parsed:
                return parsed

    label_pattern = re.compile(
        r"(?:Erstellungsdatum|Eingestellt(?:\s+am)?|Online\s+seit|Veröffentlicht(?:\s+am)?)"
        r".{0,180}?(Heute|Gestern|\d{1,2}\.\d{1,2}\.\d{4})",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = label_pattern.search(text)
    if match:
        return _parse_publication_value(match.group(1), today=today)

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
