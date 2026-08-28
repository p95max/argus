import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from alerts.kleinanzeigen import ListingViewCheck
from alerts.models import Listing


VALID_URL = "https://www.kleinanzeigen.de/s-anzeige/vw-golf/1234567890-216-1234"


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user("listing-staff", is_staff=True)


@pytest.mark.django_db
def test_live_listing_url_validation_returns_saved_public_views(client, staff_user, monkeypatch):
    client.force_login(staff_user)
    monkeypatch.setattr(
        "alerts.mobile_listings.verify_listing_url",
        lambda value: ListingViewCheck(247),
    )

    response = client.get(
        reverse("mobile_validate_kleinanzeigen_url"),
        {"url": VALID_URL},
    )

    assert response.json() == {
        "valid": True,
        "listing_id": "1234567890-216-1234",
        "status": "verified",
        "views": 247,
    }


@pytest.mark.django_db
def test_listing_can_be_saved_without_a_kleinanzeigen_url(client, staff_user):
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_create_listing"),
        {"title": "Manual listing", "is_active": "on"},
    )

    assert response.status_code == 302
    listing = Listing.objects.get(title="Manual listing")
    assert listing.kleinanzeigen_url == ""
    assert listing.views_count is None
