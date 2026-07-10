import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from alerts.models import MailboxAccount, MarketplaceAlert


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="mobile-pagination-staff",
        password="pass",
        is_staff=True,
    )


@pytest.mark.django_db
def test_mobile_dashboard_paginates_alerts_by_five(client, staff_user):
    mailbox = MailboxAccount.objects.create(
        name="Pagination inbox",
        email="pagination@example.local",
    )
    for index in range(7):
        MarketplaceAlert.objects.create(
            mailbox=mailbox,
            listing_title=f"Paged alert {index}",
            message_text="Noch da?",
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
            priority=MarketplaceAlert.Priority.NORMAL,
        )

    client.force_login(staff_user)

    first_page = client.get(f"{reverse('mobile_dashboard')}?view=all")
    second_page = client.get(f"{reverse('mobile_dashboard')}?view=all&page=2")

    assert first_page.status_code == 200
    first_body = first_page.content.decode("utf-8")
    assert first_body.count('class="card alert-card"') == 5
    assert "Showing 1-5 of 7" in first_body
    assert "?view=all&amp;page=2" in first_body
    assert "Next" in first_body

    assert second_page.status_code == 200
    second_body = second_page.content.decode("utf-8")
    assert second_body.count('class="card alert-card"') == 2
    assert "Showing 6-7 of 7" in second_body
    assert "?view=all&amp;page=1" in second_body
    assert "← Back" in second_body
