import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse

from alerts.models import Listing, MailboxAccount, MarketplaceAlert
from alerts.services.kleinanzeigen import ListingViewCheck


VALID_URL = "https://www.kleinanzeigen.de/s-anzeige/vw-golf/1234567890-216-1234"


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user("listing-staff", is_staff=True)


@pytest.mark.django_db
def test_live_listing_url_validation_checks_syntax_without_fetching_views(client, staff_user):
    client.force_login(staff_user)

    response = client.get(
        reverse("mobile_validate_kleinanzeigen_url"),
        {"url": VALID_URL},
    )

    assert response.json() == {
        "valid": True,
        "listing_id": "1234567890-216-1234",
        "status": "valid",
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


@pytest.mark.django_db
def test_url_tracker_is_bound_to_the_selected_listing_card(client, staff_user):
    client.force_login(staff_user)
    mailbox = MailboxAccount.objects.create(name="Main", email="main@example.com")
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        listing_id="marketplace-listing-42",
        listing_title="VW Golf",
    )

    response = client.post(
        reverse("mobile_configure_listing_statistics", args=[alert.id]),
        {"kleinanzeigen_url": ""},
    )

    assert response.status_code == 302
    listing = Listing.objects.get(source_alert=alert)
    assert listing.title == "VW Golf"
    assert listing.mailbox == mailbox


@pytest.mark.django_db
def test_same_kleinanzeigen_ad_uses_one_tracker_across_mailboxes(client, staff_user, monkeypatch):
    client.force_login(staff_user)
    first_mailbox = MailboxAccount.objects.create(name="One", email="one@example.com")
    second_mailbox = MailboxAccount.objects.create(name="Two", email="two@example.com")
    first = MarketplaceAlert.objects.create(
        mailbox=first_mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        listing_id="1234567890",
        listing_title="Original title",
    )
    second = MarketplaceAlert.objects.create(
        mailbox=second_mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        listing_id="1234567890",
        listing_title="Renamed title",
    )
    monkeypatch.setattr(
        "alerts.views.mobile.listings.verify_listing_url",
        lambda _url: ListingViewCheck(120),
    )

    client.post(
        reverse("mobile_configure_listing_statistics", args=[first.id]),
        {"kleinanzeigen_url": VALID_URL},
    )
    client.post(
        reverse("mobile_configure_listing_statistics", args=[second.id]),
        {"kleinanzeigen_url": VALID_URL + "?source=other-mailbox"},
    )

    assert Listing.objects.count() == 1
    listing = Listing.objects.get()
    assert listing.kleinanzeigen_listing_id == "1234567890"
    assert listing.source_alert_id == first.id
    assert listing.title == "Renamed title"

    response = client.get(reverse("mobile_listings"))
    assert len(response.context["listing_groups"]) == 1
    assert response.context["listing_groups"][0]["statistics"].id == listing.id


@pytest.mark.django_db
def test_unique_ad_id_rejects_duplicate_trackers():
    Listing.objects.create(title="First", kleinanzeigen_url=VALID_URL)

    with pytest.raises(IntegrityError):
        Listing.objects.create(
            title="Duplicate",
            kleinanzeigen_url="https://www.kleinanzeigen.de/s-anzeige/other-title/1234567890-216-9999",
        )
