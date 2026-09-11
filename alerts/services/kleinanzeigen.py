"""Safe, optional public Kleinanzeigen listing-view statistics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.db.models import Max
from django.utils import timezone

from ..models import Listing, ListingViewStat


KLEINANZEIGEN_HOSTS = {"kleinanzeigen.de", "www.kleinanzeigen.de"}
REQUEST_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 1_000_000
VIEW_COUNTER_REFRESH_INTERVAL = timedelta(hours=1)


class KleinanzeigenURLValidationError(ValueError):
    """A public, non-sensitive reason why a URL cannot be saved."""


class KleinanzeigenTemporaryError(RuntimeError):
    """The allowed public page could not be fetched or parsed right now."""


@dataclass(frozen=True)
class ValidatedListingURL:
    normalized_url: str
    listing_id: str
    ad_id: str


@dataclass(frozen=True)
class ListingViewCheck:
    views_count: int | None
    error: str = ""
    listing_status: str = Listing.KleinanzeigenStatus.UNKNOWN

    @property
    def verified(self) -> bool:
        return self.views_count is not None

    @property
    def status_verified(self) -> bool:
        return self.listing_status != Listing.KleinanzeigenStatus.UNKNOWN


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_kleinanzeigen_url(value: str) -> ValidatedListingURL:
    """Validate and normalize an HTTPS direct-listing URL before any request."""

    raw_url = (value or "").strip()
    try:
        parts = urlsplit(raw_url)
        port = parts.port
    except ValueError as exc:
        raise KleinanzeigenURLValidationError("invalid_listing_url") from exc

    if (
        parts.scheme != "https"
        or parts.hostname not in KLEINANZEIGEN_HOSTS
        or port is not None
        or parts.username is not None
        or parts.password is not None
    ):
        raise KleinanzeigenURLValidationError("invalid_listing_url")

    path_match = re.fullmatch(
        r"/s-anzeige/(?:[^/?#]+/)*(?P<listing_id>\d+(?:-\d+)*)/?",
        parts.path,
    )
    if not path_match:
        raise KleinanzeigenURLValidationError("invalid_listing_url")

    listing_id = path_match.group("listing_id")
    return ValidatedListingURL(
        normalized_url=urlunsplit(("https", "www.kleinanzeigen.de", parts.path.rstrip("/"), "", "")),
        listing_id=listing_id,
        ad_id=listing_id.split("-", 1)[0],
    )


def canonicalize_kleinanzeigen_ad_id(value: str) -> str:
    """Return Kleinanzeigen' numeric ad ID from a URL or known ID representation."""

    match = re.search(
        r"/s-anzeige/(?:[^/?#]+/)*(?P<ad_id>\d{5,})(?:-\d+)*/?",
        value or "",
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(r"(?<!\d)(?P<ad_id>\d{5,})(?:-\d+)*(?!\d)", value or "")
    return match.group("ad_id") if match else ""


def _normalize_status_markup(page_html: str) -> str:
    """Normalize HTML entities and JSON unicode escapes used in listing state labels."""

    markup = unescape(page_html or "")
    replacements = {
        r"\u00f6": "ö",
        r"\u00d6": "Ö",
        r"\u00e4": "ä",
        r"\u00c4": "Ä",
        r"\u00fc": "ü",
        r"\u00dc": "Ü",
        r"\u00df": "ß",
        r"\u00b7": "·",
        r"\u2022": "•",
        r"\u00a0": " ",
    }
    for escaped, literal in replacements.items():
        markup = markup.replace(escaped, literal).replace(escaped.upper(), literal)
    return markup


def parse_listing_status(page_html: str) -> str:
    """Extract a stable Kleinanzeigen listing state from structured or visible page markers."""

    html = _normalize_status_markup(page_html)
    deleted_patterns = (
        r'"(?:adStatus|ad[-_]?status|listingStatus|status|state)"\s*:\s*"(?:DELETED|REMOVED|EXPIRED|BLOCKED|AD_STATUS_DELETED|AD_STATUS_REMOVED)"',
        r">\s*Gelöscht\s*<",
        r"\bGelöscht\s*[•·]",
    )
    reserved_patterns = (
        r'"(?:adStatus|ad[-_]?status|listingStatus|status|state)"\s*:\s*"(?:RESERVED|AD_STATUS_RESERVED)"',
        r'"(?:isReserved|reserved)"\s*:\s*true',
        r">\s*Reserviert\s*<",
        r"\bReserviert\s*[•·]",
    )

    if any(re.search(pattern, html, flags=re.IGNORECASE) for pattern in deleted_patterns):
        return Listing.KleinanzeigenStatus.DELETED
    if any(re.search(pattern, html, flags=re.IGNORECASE) for pattern in reserved_patterns):
        return Listing.KleinanzeigenStatus.RESERVED

    active_patterns = (
        r'"(?:adStatus|ad[-_]?status|listingStatus|status|state)"\s*:\s*"(?:ACTIVE|AD_STATUS_ACTIVE)"',
        r'\bid\s*=\s*["\']viewad-main["\']',
    )
    if any(re.search(pattern, html, flags=re.IGNORECASE) for pattern in active_patterns):
        return Listing.KleinanzeigenStatus.ACTIVE
    return Listing.KleinanzeigenStatus.UNKNOWN


def parse_views_count(page_html: str) -> int | None:
    """Extract the public view count from known structured/text page variants."""

    patterns = (
        r'<[^>]+\bid\s*=\s*["\']viewad-cntr-num["\'][^>]*>\s*(\d[\d.\s,]*)\s*</',
        r'"(?:viewCount|views)"\s*:\s*"?(\d[\d.\s,]*)"?',
        r"(\d[\d.\s,]*)\s*(?:mal\s+angesehen|aufrufe|views)",
    )
    for pattern in patterns:
        match = re.search(pattern, page_html or "", flags=re.IGNORECASE)
        if not match:
            continue
        digits = re.sub(r"\D", "", match.group(1))
        if digits:
            return int(digits)
    return None


def parse_view_counter_response(payload: bytes) -> int | None:
    """Extract ``numVisits`` from Kleinanzeigen's public ViewCount response."""

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    value = data.get("numVisits") if isinstance(data, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _view_counter_url(validated: ValidatedListingURL) -> str:
    """Build the only allowed ViewCount endpoint from a validated listing ID."""

    ad_id = validated.ad_id
    if not ad_id.isdecimal():
        raise KleinanzeigenTemporaryError("listing_unavailable")
    return f"https://www.kleinanzeigen.de/s-vac-inc-get.json?adId={ad_id}"


def _fetch_payload(url: str, *, opener, referer: str = "") -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)

    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status < 200 or status >= 300:
                raise KleinanzeigenTemporaryError("listing_unavailable")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            response.close()
    except HTTPError as exc:
        raise KleinanzeigenTemporaryError("listing_unavailable") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise KleinanzeigenTemporaryError("listing_unavailable") from exc

    if len(payload) > MAX_RESPONSE_BYTES:
        raise KleinanzeigenTemporaryError("listing_unavailable")
    return payload


def fetch_listing_check(url: str, *, opener=None) -> ListingViewCheck:
    """Fetch a listing once and extract both marketplace status and view count."""

    validated = validate_kleinanzeigen_url(url)
    opener = opener or build_opener(_NoRedirectHandler())
    page_payload = _fetch_payload(validated.normalized_url, opener=opener)
    page_html = page_payload.decode("utf-8", errors="replace")
    listing_status = parse_listing_status(page_html)

    if listing_status == Listing.KleinanzeigenStatus.DELETED:
        return ListingViewCheck(None, listing_status=listing_status)

    views_count = parse_views_count(page_html)
    if views_count is not None:
        return ListingViewCheck(views_count, listing_status=listing_status)

    counter_payload = _fetch_payload(
        _view_counter_url(validated),
        opener=opener,
        referer=validated.normalized_url,
    )
    views_count = parse_view_counter_response(counter_payload)
    if views_count is None:
        return ListingViewCheck(
            None,
            "listing_unavailable",
            listing_status=listing_status,
        )
    return ListingViewCheck(views_count, listing_status=listing_status)


def fetch_listing_views(url: str, *, opener=None) -> int:
    """Fetch the public view count while keeping the legacy integer API."""

    result = fetch_listing_check(url, opener=opener)
    if result.views_count is None:
        raise KleinanzeigenTemporaryError("listing_unavailable")
    return result.views_count


def verify_listing_url(value: str, *, opener=None) -> ListingViewCheck:
    """Return a safe, user-facing verification state without leaking internals."""

    validated = validate_kleinanzeigen_url(value)
    try:
        return fetch_listing_check(validated.normalized_url, opener=opener)
    except Exception:
        return ListingViewCheck(None, "listing_unavailable")


def _repair_decreasing_view_history(listing: Listing) -> int | None:
    """Drop decreasing snapshots and restore the current counter from valid history."""

    historical_max = listing.view_stats.aggregate(value=Max("views_count"))["value"]
    if historical_max is None:
        return listing.views_count

    running_max = None
    invalid_ids = []
    for snapshot in listing.view_stats.order_by("created_at", "id").only("id", "views_count"):
        if running_max is not None and snapshot.views_count < running_max:
            invalid_ids.append(snapshot.id)
            continue
        running_max = snapshot.views_count

    if invalid_ids:
        ListingViewStat.objects.filter(id__in=invalid_ids).delete()

    if listing.views_count is None or listing.views_count < historical_max:
        listing.views_count = historical_max
        listing.save(update_fields=["views_count", "updated_at"])

    return historical_max


def repair_listing_view_counters(listings=None) -> int:
    """Repair already-corrupted current counters from saved monotonic history."""

    queryset = listings if listings is not None else Listing.objects.exclude(kleinanzeigen_url="")
    repaired = 0
    for listing in queryset:
        before = listing.views_count
        _repair_decreasing_view_history(listing)
        if listing.views_count != before:
            repaired += 1
    return repaired


def _save_listing_status(listing: Listing, result: ListingViewCheck) -> bool:
    """Persist only a verified marketplace status, preserving the last known state on errors."""

    if not result.status_verified or listing.kleinanzeigen_status == result.listing_status:
        return False
    listing.kleinanzeigen_status = result.listing_status
    return True


def refresh_listing_view_stats(*, fetcher=verify_listing_url) -> tuple[int, int]:
    """Update listing status and views without allowing the public counter to move backwards."""

    checked = 0
    updated = 0
    refresh_before = timezone.now() - VIEW_COUNTER_REFRESH_INTERVAL
    for listing in Listing.objects.exclude(kleinanzeigen_url="").iterator():
        historical_floor = _repair_decreasing_view_history(listing)

        # A deleted Kleinanzeigen ad is terminal. Keep its Argus history, but stop polling it.
        if listing.kleinanzeigen_status == Listing.KleinanzeigenStatus.DELETED:
            continue
        recently_checked = listing.views_checked_at and listing.views_checked_at >= refresh_before
        if recently_checked and listing.kleinanzeigen_status != Listing.KleinanzeigenStatus.UNKNOWN:
            continue

        checked += 1
        now = timezone.now()
        try:
            result = fetcher(listing.kleinanzeigen_url)
        except Exception:
            listing.views_error = "listing_unavailable"
            listing.views_checked_at = now
            listing.save(update_fields=["views_error", "views_checked_at", "updated_at"])
            continue

        status_changed = _save_listing_status(listing, result)
        if result.listing_status == Listing.KleinanzeigenStatus.DELETED:
            listing.views_error = ""
            listing.views_checked_at = now
            update_fields = ["views_error", "views_checked_at", "updated_at"]
            if status_changed:
                update_fields.append("kleinanzeigen_status")
            listing.save(update_fields=update_fields)
            continue

        if not result.verified:
            listing.views_error = result.error
            listing.views_checked_at = now
            update_fields = ["views_error", "views_checked_at", "updated_at"]
            if status_changed:
                update_fields.append("kleinanzeigen_status")
            listing.save(update_fields=update_fields)
            continue

        safe_floor = historical_floor
        if listing.views_count is not None:
            safe_floor = max(safe_floor or 0, listing.views_count)

        if safe_floor is not None and result.views_count < safe_floor:
            listing.views_error = "view_counter_decreased"
            listing.views_checked_at = now
            update_fields = ["views_error", "views_checked_at", "updated_at"]
            if status_changed:
                update_fields.append("kleinanzeigen_status")
            listing.save(update_fields=update_fields)
            continue

        changed = listing.views_count != result.views_count
        listing.views_count = result.views_count
        listing.views_checked_at = now
        listing.views_error = ""
        update_fields = ["views_count", "views_checked_at", "views_error", "updated_at"]
        if status_changed:
            update_fields.append("kleinanzeigen_status")
        listing.save(update_fields=update_fields)
        if changed:
            ListingViewStat.objects.create(listing=listing, views_count=result.views_count)
            updated += 1

    return checked, updated
