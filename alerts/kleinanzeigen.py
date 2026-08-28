"""Safe, optional public Kleinanzeigen listing-view statistics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.utils import timezone

from .models import Listing, ListingViewStat


KLEINANZEIGEN_HOSTS = {"kleinanzeigen.de", "www.kleinanzeigen.de"}
REQUEST_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 1_000_000


class KleinanzeigenURLValidationError(ValueError):
    """A public, non-sensitive reason why a URL cannot be saved."""


class KleinanzeigenTemporaryError(RuntimeError):
    """The allowed public page could not be fetched or parsed right now."""


@dataclass(frozen=True)
class ValidatedListingURL:
    normalized_url: str
    listing_id: str


@dataclass(frozen=True)
class ListingViewCheck:
    views_count: int | None
    error: str = ""

    @property
    def verified(self) -> bool:
        return self.views_count is not None


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

    return ValidatedListingURL(
        normalized_url=urlunsplit(("https", "www.kleinanzeigen.de", parts.path.rstrip("/"), "", "")),
        listing_id=path_match.group("listing_id"),
    )


def parse_views_count(page_html: str) -> int | None:
    """Extract the public view count from known structured/text page variants."""

    patterns = (
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


def fetch_listing_views(url: str, *, opener=None) -> int:
    """Fetch an already validated URL without cookies or redirect following."""

    validated = validate_kleinanzeigen_url(url)
    opener = opener or build_opener(_NoRedirectHandler())
    request = Request(
        validated.normalized_url,
        headers={"User-Agent": "Argus listing statistics/1.0"},
    )

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

    views_count = parse_views_count(payload.decode("utf-8", errors="replace"))
    if views_count is None:
        raise KleinanzeigenTemporaryError("listing_unavailable")
    return views_count


def verify_listing_url(value: str, *, opener=None) -> ListingViewCheck:
    """Return a safe, user-facing verification state without leaking internals."""

    validated = validate_kleinanzeigen_url(value)
    try:
        return ListingViewCheck(fetch_listing_views(validated.normalized_url, opener=opener))
    except Exception:
        return ListingViewCheck(None, "listing_unavailable")


def refresh_listing_view_stats(*, fetcher=verify_listing_url) -> tuple[int, int]:
    """Update all configured listings; a failure never affects listing activity."""

    checked = 0
    updated = 0
    for listing in Listing.objects.exclude(kleinanzeigen_url="").iterator():
        checked += 1
        try:
            result = fetcher(listing.kleinanzeigen_url)
        except Exception:
            listing.views_error = "listing_unavailable"
            listing.save(update_fields=["views_error", "updated_at"])
            continue
        if not result.verified:
            listing.views_error = result.error
            listing.save(update_fields=["views_error", "updated_at"])
            continue

        now = timezone.now()
        changed = listing.views_count != result.views_count
        listing.views_count = result.views_count
        listing.views_checked_at = now
        listing.views_error = ""
        listing.save(
            update_fields=["views_count", "views_checked_at", "views_error", "updated_at"]
        )
        if changed:
            ListingViewStat.objects.create(listing=listing, views_count=result.views_count)
            updated += 1

    return checked, updated
