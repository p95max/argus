import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from alerts.models import MailboxAccount


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.local",
        password="pass",
    )


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(
        name="Admin Gmail",
        email="admin-gmail@example.local",
        is_active=True,
        gmail_connected_email="admin-gmail@example.local",
        gmail_oauth_token="token",
    )


@pytest.mark.django_db
def test_admin_gmail_actions_render_post_buttons(client, superuser, mailbox):
    client.force_login(superuser)
    check_url = reverse("admin:alerts_mailboxaccount_gmail_check_now", args=[mailbox.id])
    disconnect_url = reverse("admin:alerts_mailboxaccount_gmail_disconnect", args=[mailbox.id])

    response = client.get(reverse("admin:alerts_mailboxaccount_change", args=[mailbox.id]))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert f'href="{check_url}"' not in body
    assert f'href="{disconnect_url}"' not in body
    assert f'formaction="{check_url}"' in body
    assert f'formaction="{disconnect_url}"' in body
    assert 'formmethod="post"' in body
    assert 'csrfmiddlewaretoken' in body


@pytest.mark.django_db
def test_admin_gmail_disconnect_rejects_get(client, superuser, mailbox):
    client.force_login(superuser)

    response = client.get(
        reverse("admin:alerts_mailboxaccount_gmail_disconnect", args=[mailbox.id])
    )

    assert response.status_code == 405
    mailbox.refresh_from_db()
    assert mailbox.gmail_oauth_token == "token"
    assert mailbox.gmail_connected_email == "admin-gmail@example.local"


@pytest.mark.django_db
def test_admin_gmail_check_now_rejects_get(client, superuser, mailbox):
    client.force_login(superuser)

    response = client.get(
        reverse("admin:alerts_mailboxaccount_gmail_check_now", args=[mailbox.id])
    )

    assert response.status_code == 405


@pytest.mark.django_db
def test_admin_gmail_disconnect_requires_csrf(superuser, mailbox):
    client = Client(enforce_csrf_checks=True)
    client.force_login(superuser)

    response = client.post(
        reverse("admin:alerts_mailboxaccount_gmail_disconnect", args=[mailbox.id])
    )

    assert response.status_code == 403
    mailbox.refresh_from_db()
    assert mailbox.gmail_oauth_token == "token"
    assert mailbox.gmail_connected_email == "admin-gmail@example.local"


@pytest.mark.django_db
def test_admin_gmail_check_now_requires_csrf(superuser, mailbox):
    client = Client(enforce_csrf_checks=True)
    client.force_login(superuser)

    response = client.post(
        reverse("admin:alerts_mailboxaccount_gmail_check_now", args=[mailbox.id])
    )

    assert response.status_code == 403
