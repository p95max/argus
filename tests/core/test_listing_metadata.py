from datetime import date, timedelta

import pytest

from alerts.services.listing_metadata import parse_listing_publication_date


def test_publication_date_parser_handles_current_vip_date_element():
    page_html = """
        <span id="vip-ad-creationdate"
              class="ad-keydetails--ad-date icon-calendar-gray">10.09.2026</span>
    """

    assert parse_listing_publication_date(page_html, today=date(2026, 9, 11)) == date(
        2026, 9, 10
    )


@pytest.mark.parametrize(
    ("label", "expected_delta"),
    [
        ("Heute, 14:51", timedelta()),
        ("Gestern, 23:59", timedelta(days=1)),
    ],
)
def test_publication_date_parser_keeps_current_relative_dates(label, expected_delta):
    today = date(2026, 9, 11)
    page_html = f"""
        <div>Ähnliche Anzeige vom 01.01.2020</div>
        <span class="ad-keydetails--ad-date" id="vip-ad-creationdate">{label}</span>
    """

    assert parse_listing_publication_date(page_html, today=today) == today - expected_delta
