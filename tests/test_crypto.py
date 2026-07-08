import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import alerts
from alerts.apps import AlertsConfig
from alerts.crypto import _fernet, decrypt_text, encrypt_text


def test_gmail_token_crypto_roundtrip_with_explicit_key():
    key = Fernet.generate_key().decode("ascii")

    with override_settings(DEBUG=False, GMAIL_OAUTH_TOKEN_FERNET_KEY=key):
        encrypted = encrypt_text("refresh-token")

        assert encrypted.startswith("fernet:")
        assert decrypt_text(encrypted) == "refresh-token"


def test_gmail_token_crypto_rejects_missing_key_in_production():
    with override_settings(
        DEBUG=False,
        GMAIL_OAUTH_TOKEN_FERNET_KEY="",
        SECRET_KEY="test-secret",
    ):
        with pytest.raises(ImproperlyConfigured, match="GMAIL_OAUTH_TOKEN_FERNET_KEY"):
            _fernet()


def test_gmail_token_crypto_keeps_secret_key_fallback_only_in_debug():
    with override_settings(
        DEBUG=True,
        GMAIL_OAUTH_TOKEN_FERNET_KEY="",
        SECRET_KEY="test-secret",
    ):
        encrypted = encrypt_text("dev-refresh-token")

        assert encrypted.startswith("fernet:")
        assert decrypt_text(encrypted) == "dev-refresh-token"


def test_alerts_app_ready_hardstops_missing_fernet_key_in_production():
    config = AlertsConfig("alerts", alerts)

    with override_settings(DEBUG=False, GMAIL_OAUTH_TOKEN_FERNET_KEY=""):
        with pytest.raises(ImproperlyConfigured, match="GMAIL_OAUTH_TOKEN_FERNET_KEY"):
            config.ready()
