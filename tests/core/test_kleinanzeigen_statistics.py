from datetime import timedelta

import pytest
from django.utils import timezone

from alerts.kleinanzeigen import (
    KleinanzeigenURLValidationError,
    ListingViewCheck,
    parse_views_count,
    refresh_listing_view_stats,
    validate_kleinanzeigen_url,
    verify_listing_url,
)
from alerts.listing_analytics import get_listing_analytics
from alerts.models import Listing, ListingViewStat


VALID_URL = "https://www.kleinanzeigen.de/s-anzeige/vw-golf/1234567890-216-1234"


def test_valid_listing_url_is_normalized_and_keeps_external_id():
    validated = validate_kleinanzeigen_url(VALID_URL + "?utm_source=x#details")

    assert validated.normalized_url == VALID_URL
    assert validated.listing_id == "1234567890-216-1234"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.kleinanzeigen.de/s-anzeige/vw-golf/1234567890-216-1234",
        "https://example.com/s-anzeige/vw-golf/1234567890-216-1234",
        "https://localhost/s-anzeige/vw-golf/1234567890-216-1234",
        "https://www.kleinanzeigen.de/s-suchanfrage.html",
        "https://www.kleinanzeigen.de/profil/example",
        "https://www.kleinanzeigen.de:444/s-anzeige/vw-golf/1234567890-216-1234",
    ],
)
def test_only_direct_https_kleinanzeigen_listing_urls_are_accepted(url):
    with pytest.raises(KleinanzeigenURLValidationError):
        validate_kleinanzeigen_url(url)


def test_views_parser_handles_structured_and_visible_counts():
    assert parse_views_count('{"viewCount": "1.284"}') == 1284
    assert parse_views_count("Bereits 427 mal angesehen") == 427
    assert parse_views_count("No public count") is None


def test_temporary_verification_error_keeps_url_syntactically_valid(monkeypatch):
    monkeypatch.setattr(
        "alerts.kleinanzeigen.fetch_listing_views",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")),
    )

    result = verify_listing_url(VALID_URL)

    assert result.verified is False
    assert result.error == "listing_unavailable"


@pytest.mark.django_db
def test_snapshot_is_created_only_when_the_view_count_changes():
    listing = Listing.objects.create(title="VW Golf", kleinanzeigen_url=VALID_URL)

    refresh_listing_view_stats(fetcher=lambda _: ListingViewCheck(100))
    refresh_listing_view_stats(fetcher=lambda _: ListingViewCheck(100))
    refresh_listing_view_stats(fetcher=lambda _: ListingViewCheck(101))

    assert list(listing.view_stats.values_list("views_count", flat=True)) == [101, 100]


@pytest.mark.django_db
def test_analytics_uses_saved_data_and_sorts_by_24_hour_growth():
    now = timezone.now()
    slow = Listing.objects.create(title="iPhone", kleinanzeigen_url=VALID_URL, views_count=286)
    fast = Listing.objects.create(title="VW Golf", kleinanzeigen_url=VALID_URL, views_count=427)
    fresh = Listing.objects.create(title="Fresh", kleinanzeigen_url=VALID_URL, views_count=5)
    ListingViewStat.objects.create(listing=slow, views_count=264)
    ListingViewStat.objects.create(listing=fast, views_count=396)
    ListingViewStat.objects.filter(listing__in=[slow, fast]).update(created_at=now - timedelta(hours=25))
    ListingViewStat.objects.create(listing=fresh, views_count=5)

    analytics = get_listing_analytics(now=now)

    assert analytics.total_views == 718
    assert analytics.total_delta_24h == 53
    assert [item.title for item in analytics.listings] == ["VW Golf", "iPhone", "Fresh"]
    assert [item.views_delta_24h for item in analytics.listings] == [31, 22, None]
