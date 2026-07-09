import pytest
from django.core.cache import cache
from django.urls import reverse


@pytest.mark.django_db
def test_admin_login_rate_limit_blocks_repeated_failures(client, django_user_model, settings):
    settings.ADMIN_LOGIN_FAILURE_LIMIT = 2
    settings.ADMIN_LOGIN_LOCKOUT_SECONDS = 60
    cache.clear()
    django_user_model.objects.create_superuser(
        username="admin",
        email="admin@example.local",
        password="correct-password",
    )
    login_url = reverse("admin:login")

    first = client.post(login_url, {"username": "admin", "password": "wrong"})
    second = client.post(login_url, {"username": "admin", "password": "wrong"})
    blocked = client.post(login_url, {"username": "admin", "password": "wrong"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429
