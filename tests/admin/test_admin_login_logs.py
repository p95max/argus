import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from alerts.models import AdminLoginLog


@pytest.mark.django_db
def test_successful_admin_login_is_recorded_with_request_details(client):
    user = get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.local",
        password="correct-password",
    )
    login_url = reverse("admin:login")

    response = client.post(
        login_url,
        {"username": "admin", "password": "correct-password"},
        REMOTE_ADDR="203.0.113.10",
        HTTP_USER_AGENT="Argus test browser",
    )

    assert response.status_code == 302
    entry = AdminLoginLog.objects.get()
    assert entry.user == user
    assert entry.ip_address == "203.0.113.10"
    assert entry.user_agent == "Argus test browser"
    assert entry.path == login_url
    assert entry.logged_out_at is None


@pytest.mark.django_db
def test_admin_logout_records_logout_time(client):
    get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.local",
        password="correct-password",
    )
    client.post(
        reverse("admin:login"),
        {"username": "admin", "password": "correct-password"},
    )

    client.post(reverse("admin:logout"))

    assert AdminLoginLog.objects.get().logged_out_at is not None


@pytest.mark.django_db
def test_failed_admin_login_is_not_recorded(client):
    get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.local",
        password="correct-password",
    )

    client.post(
        reverse("admin:login"),
        {"username": "admin", "password": "wrong-password"},
    )

    assert not AdminLoginLog.objects.exists()
