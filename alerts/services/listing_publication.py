import re
from datetime import timedelta
from html import unescape

from django.utils import timezone

from ..listing_tombstones import DeletedListingIdentifier
from ..models import Listing, MarketplaceAlert
from .kleinanzeigen import (
    KleinanzeigenURLValidationError,
    canonicalize_kleinanzeigen_ad_id,
    validate_kleinanzeigen_url,
)


PUBLICATION_PATTERNS = (
    r"\banzeige wurde erfolgreich ver(?:ö|oe)ffentlicht\b",
    r"\berfolgreich ver(?:ö|oe)ffentlicht\b",
)
TOMBSTONE_RETENTION = timedelta(days=30)
SUPPORTED_LISTING_ALERT_TYPES = {
    MarketplaceAlert.EventType.SYSTEM_NOTICE,
    MarketplaceAlert.EventType.BUYER_MESSAGE,
}


def _looks_like_publication_notice(alert: MarketplaceAlert) -> bool:
    if alert.event_type != MarketplaceAlert.EventType.SYSTEM_NOTICE:
        return False
    text = unescape(f"{alert.raw_subject}\n{alert.raw_body}\n{alert.normalized_body}").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in PUBLICATION_PATTERNS)


def _supports_listing_action(alert: MarketplaceAlert) -> bool:
    return alert.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE or _looks_like_publication_notice(alert)


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
    value = (alert.listing_id or "").strip()
    if not value.startswith("https://"):
        return ""
    try:
        return validate_kleinanzeigen_url(value).normalized_url
    except KleinanzeigenURLValidationError:
        return ""


def _alert_listing_id(alert: MarketplaceAlert, listing_url: str = "") -> str:
    if listing_url:
        try:
            return validate_kleinanzeigen_url(listing_url).ad_id
        except KleinanzeigenURLValidationError:
            pass
    value = (alert.listing_id or "").strip()
    return canonicalize_kleinanzeigen_ad_id(value) or ""


def prune_expired_listing_tombstones() -> int:
    """Delete deleted-listing tombstones older than 30 days."""
    cutoff = timezone.now() - TOMBSTONE_RETENTION
    deleted, _ = DeletedListingIdentifier.objects.filter(deleted_at__lt=cutoff).delete()
    return deleted


def listing_alert_info(alert: MarketplaceAlert) -> dict[str, str]:
    """Return listing state, ID and URL for publication or buyer-message alerts."""
    if not _supports_listing_action(alert):
        return {"state": "not_supported", "listing_id": "", "listing_url": ""}

    listing_url = _extract_listing_url(alert) or _url_from_listing_id(alert)
    listing_id = _alert_listing_id(alert, listing_url)
    if not listing_id:
        return {"state": "missing_id", "listing_id": "", "listing_url": listing_url}

    prune_expired_listing_tombstones()
    if DeletedListingIdentifier.objects.filter(kleinanzeigen_listing_id=listing_id).exists():
        state = "deleted"
    elif Listing.objects.filter(kleinanzeigen_listing_id=listing_id).exists():
        state = "existing"
    elif listing_url:
        state = "available"
    else:
        state = "missing_url"

    return {"state": state, "listing_id": listing_id, "listing_url": listing_url}


def publication_listing_state(alert: MarketplaceAlert) -> str:
    """Backward-compatible state helper used by the alert UI."""
    return listing_alert_info(alert)["state"]


def publication_listing_candidate(alert: MarketplaceAlert):
    """Return a validated listing when this alert can create a tracker."""
    info = listing_alert_info(alert)
    if info["state"] != "available" or not info["listing_url"]:
        return None
    return validate_kleinanzeigen_url(info["listing_url"])


def sync_listing_from_publication(alert: MarketplaceAlert) -> Listing | None:
    """Create a tracker from a publication or buyer-message alert when possible."""
    candidate = publication_listing_candidate(alert)
    if candidate is None:
        return None

    existing = Listing.objects.filter(kleinanzeigen_listing_id=candidate.ad_id).first()
    if existing is not None:
        return existing

    title = (alert.listing_title or alert.subject or f"Kleinanzeigen {candidate.ad_id}").strip()
    return Listing.objects.create(
        title=title[:255],
        source_alert=alert,
        mailbox=alert.mailbox,
        kleinanzeigen_url=candidate.normalized_url,
        kleinanzeigen_listing_id=candidate.ad_id,
        is_active=True,
    )


def tombstone_listing_id(listing_id: str) -> None:
    listing_id = (listing_id or "").strip()
    if not listing_id:
        return

    prune_expired_listing_tombstones()
    DeletedListingIdentifier.objects.get_or_create(kleinanzeigen_listing_id=listing_id)
