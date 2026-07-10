from django.test import RequestFactory, override_settings

from alerts.security import _client_ip


factory = RequestFactory()


def _request(remote_addr="198.51.100.10", forwarded_for=""):
    request = factory.post("/control/login/", {"username": "admin"})
    request.META["REMOTE_ADDR"] = remote_addr
    if forwarded_for:
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return request


@override_settings(ADMIN_LOGIN_TRUSTED_PROXY_IPS=[])
def test_admin_login_client_ip_ignores_x_forwarded_for_by_default():
    request = _request(
        remote_addr="127.0.0.1",
        forwarded_for="203.0.113.10",
    )

    assert _client_ip(request) == "127.0.0.1"


@override_settings(ADMIN_LOGIN_TRUSTED_PROXY_IPS=[])
def test_admin_login_client_ip_cannot_be_spoofed_without_trusted_proxy_config():
    request = _request(
        remote_addr="198.51.100.20",
        forwarded_for="203.0.113.10",
    )

    assert _client_ip(request) == "198.51.100.20"


@override_settings(ADMIN_LOGIN_TRUSTED_PROXY_IPS=["127.0.0.1"])
def test_admin_login_client_ip_uses_forwarded_for_from_trusted_proxy():
    request = _request(
        remote_addr="127.0.0.1",
        forwarded_for="203.0.113.10",
    )

    assert _client_ip(request) == "203.0.113.10"


@override_settings(ADMIN_LOGIN_TRUSTED_PROXY_IPS=["127.0.0.1"])
def test_admin_login_client_ip_prefers_rightmost_untrusted_forwarded_ip():
    request = _request(
        remote_addr="127.0.0.1",
        forwarded_for="198.51.100.55, 203.0.113.10",
    )

    assert _client_ip(request) == "203.0.113.10"


@override_settings(ADMIN_LOGIN_TRUSTED_PROXY_IPS=["127.0.0.1", "10.0.0.0/8"])
def test_admin_login_client_ip_skips_trusted_forwarded_proxy_chain():
    request = _request(
        remote_addr="127.0.0.1",
        forwarded_for="203.0.113.10, 10.0.0.15",
    )

    assert _client_ip(request) == "203.0.113.10"


@override_settings(ADMIN_LOGIN_TRUSTED_PROXY_IPS=["127.0.0.1"])
def test_admin_login_client_ip_falls_back_to_remote_addr_when_forwarded_chain_is_empty():
    request = _request(remote_addr="127.0.0.1")

    assert _client_ip(request) == "127.0.0.1"
