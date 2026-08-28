import pytest

from alerts.listing_analytics import ListingAnalytics, ListingAnalyticsItem
from alerts.telegram.messages import build_apps_analytics_message


@pytest.mark.django_db
def test_apps_analytics_message_is_omitted_without_data():
    assert build_apps_analytics_message(analytics=None) is None


def test_apps_analytics_message_is_compact_and_orders_precomputed_items():
    analytics = ListingAnalytics(
        total_views=1284,
        total_delta_24h=63,
        listings=(
            ListingAnalyticsItem(1, "VW Golf", 427, 31),
            ListingAnalyticsItem(2, "iPhone", 286, 22),
        ),
    )

    text = build_apps_analytics_message(analytics)

    assert "📊 <b>Аналитика</b>" in text
    assert "👁 <b>Просмотры:</b> 1 284" in text
    assert "📈 <b>За 24 ч:</b> +63" in text
    assert text.index("VW Golf") < text.index("iPhone")
