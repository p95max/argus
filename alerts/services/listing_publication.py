import re
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from ..listing_tombstones import DeletedListingIdentifier
from ..models import Listing, MarketplaceAlert
from .kleinanzeigen import KleinanzeigenURLValidationError, validate_kleinanzeigen_url


PUBLICATION_PATTERNS = (
    r"\banzeige wurde erfolgreich ver(?:ö|oe)ffentlicht\b",
    r"\berfolgreich ver(?:ö|oe)ffentlicht\b",
)


def _looks_like_publication_notice(alert: MarketplaceAlert) -> bool:
    if alert.event_type != MarketplaceAlert.EventType.SYSTEM_NOTICE:
        return False
    text = unescape(f"{alert.raw_subject}\n{alert.raw_body}\n{alert.normalized_body}").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in PUBLICATION_PATTERNS)


def _extract_listing_url(alert: MarketplaceAlert) -> str:
    text = unescape(f"{alert.raw_body}\n{alert.normalized_body}")
    candidates = re.findall(
        r"https://(?:www\.)?kleinanzeigen\.de/s-anzeige/[^\s\"'<>]+",
        text,
        flags=re.IGNORECASE,
    )
    for candidate in candidates:
        candidate = candidate.rstrip(".,);]")
        try:
            return validate_kleinanzeigen_url(candidate).normalized_url
        except KleinanzeigenURLValidationError:
            continue
    return ""


def _url_from_listing_id(alert: MarketplaceAlert) -> str:
    """Recover a direct listing URL from a matching URL-shaped ID source when possible."""
    value = (alert.listing_id or "").strip()
    if not value.startswith("https://"):
        return ""
    try:
        return validate_kleinanzeigen_url(value).normalized_url
    except KleinanzeigenURLValidationError:
        return ""


def sync_listing_from_publication(alert: MarketplaceAlert) -> Listing | None:
    """Create a tracker for a publication notice unless its Kleinanzeigen ID is known/deleted."""
    if not _looks_like_publication_notice(alert):
        return None

    listing_url = _extract_listing_url(alert) or _url_from_listing_id(alert)
    if not listing_url:
        return None

    validated = validate_kleinanzeigen_url(listing_url)
    ad_id = validated.ad_id
    if DeletedListingIdentifier.objects.filter(kleinanzeigen_listing_id=ad_id).exists():
        return None

    existing = Listing.objects.filter(kleinanzeigen_listing_id=ad_id).first()
    if existing is not None:
        return existing

    title = (alert.listing_title or alert.subject or f"Kleinanzeigen {ad_id}").strip()
    return Listing.objects.create(
        title=title[:255],
        source_alert=alert,
        mailbox=alert.mailbox,
        kleinanzeigen_url=validated.normalized_url,
        kleinanzeigen_listing_id=ad_id,
        is_active=True,
    )


def tombstone_listing_id(listing_id: str) -> None:
    listing_id = (listing_id or "").strip()
    if not listing_id:
        return
    DeletedListingIdentifier.objects.get_or_create(kleinanzeigen_listing_id=listing_id)
