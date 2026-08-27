import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from alerts.models import MailboxAccount, MarketplaceAlert


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="mobile-staff",
        password="test-pass",
        is_staff=True,
    )


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(
        name="Kleinanzeigen",
        email="seller@example.com",
        is_active=True,
    )


def create_alert(mailbox, *, listing_id, listing_title, buyer_name, status="unread"):
    return MarketplaceAlert.objects.create(
        mailbox=mailbox,
        event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
        alert_status=status,
        priority=MarketplaceAlert.Priority.NORMAL,
        parse_status=MarketplaceAlert.ParseStatus.SUCCESS,
        listing_id=listing_id,
        listing_title=listing_title,
        buyer_name=buyer_name,
        message_text=f"Message from {buyer_name}",
    )


@pytest.mark.django_db
def test_mobile_listings_groups_multiple_leads_under_one_listing(client, staff_user, mailbox):
    first = create_alert(
        mailbox,
        listing_id="3496170238",
        listing_title="Skoda Octavia 1.4 tsi 122 ps, tüv neu",
        buyer_name="Thomas",
    )
    second = create_alert(
        mailbox,
        listing_id="3496170238",
        listing_title="Skoda Octavia 1.4 tsi 122 ps, tüv neu",
        buyer_name="Anna",
    )
    create_alert(
        mailbox,
        listing_id="other-listing",
        listing_title="VW Golf",
        buyer_name="Max",
    )
    client.force_login(staff_user)

    response = client.get(reverse("mobile_listings"))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert body.count("Skoda Octavia 1.4 tsi 122 ps, tüv neu") == 1
    assert f"Обращение #{first.id}" in body
    assert f"Обращение #{second.id}" in body
    assert "Thomas" in body
    assert "Anna" in body
    assert "2 активных" in body


@pytest.mark.django_db
def test_mobile_processed_action_archives_only_selected_lead(client, staff_user, mailbox):
    selected = create_alert(
        mailbox,
        listing_id="3496170238",
        listing_title="Skoda Octavia",
        buyer_name="Thomas",
    )
    untouched = create_alert(
        mailbox,
        listing_id="3496170238",
        listing_title="Skoda Octavia",
        buyer_name="Anna",
    )
    client.force_login(staff_user)

    response = client.post(
        reverse("mobile_update_alert_status", args=[selected.id]),
        {
            "status": MarketplaceAlert.AlertStatus.ARCHIVED,
            "next": reverse("mobile_listings"),
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("mobile_listings")
    selected.refresh_from_db()
    untouched.refresh_from_db()
    assert selected.alert_status == MarketplaceAlert.AlertStatus.ARCHIVED
    assert untouched.alert_status == MarketplaceAlert.AlertStatus.UNREAD


@pytest.mark.django_db
def test_mobile_dashboard_and_detail_show_processed_button(client, staff_user, mailbox):
    alert = create_alert(
        mailbox,
        listing_id="3496170238",
        listing_title="Skoda Octavia",
        buyer_name="Thomas",
    )
    client.force_login(staff_user)

    dashboard = client.get(reverse("mobile_dashboard") + "?view=all")
    detail = client.get(reverse("mobile_alert_detail", args=[alert.id]))

    assert dashboard.status_code == 200
    assert detail.status_code == 200
    assert "Обращение обработано" in dashboard.content.decode("utf-8")
    assert "Обращение обработано" in detail.content.decode("utf-8")
    assert reverse("mobile_listings") in dashboard.content.decode("utf-8")
    assert reverse("mobile_listings") in detail.content.decode("utf-8")
