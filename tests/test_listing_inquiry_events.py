import pytest
from django.utils import timezone

from alerts.models import (
    Listing,
    ListingInquiryEvent,
    MailboxAccount,
    MarketplaceAlert,
)


@pytest.mark.django_db
def test_inquiry_event_survives_alert_and_listing_deletion():
    mailbox = MailboxAccount.objects.create(
        name="Analytics mailbox",
        email="analytics@example.local",
    )
    listing = Listing.objects.create(
        title="Persistent analytics listing",
        kleinanzeigen_listing_id="1234567890",
    )
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        listing_id=listing.kleinanzeigen_listing_id,
        listing_title=listing.title,
        subject="Buyer inquiry",
        received_at=timezone.now(),
    )

    event = ListingInquiryEvent.objects.get(source_alert_id=alert.id)
    assert event.listing_id == listing.id
    assert event.kleinanzeigen_listing_id == "1234567890"
    assert event.listing_title == "Persistent analytics listing"

    alert.delete()
    event.refresh_from_db()
    assert ListingInquiryEvent.objects.filter(pk=event.pk).exists()

    listing.delete()
    event.refresh_from_db()
    assert event.listing_id is None
    assert event.kleinanzeigen_listing_id == "1234567890"
    assert event.listing_title == "Persistent analytics listing"


@pytest.mark.django_db
def test_non_buyer_alert_does_not_create_inquiry_event():
    mailbox = MailboxAccount.objects.create(
        name="System mailbox",
        email="system@example.local",
    )
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.SYSTEM_NOTICE,
        subject="System notice",
    )

    assert not ListingInquiryEvent.objects.filter(source_alert_id=alert.id).exists()
