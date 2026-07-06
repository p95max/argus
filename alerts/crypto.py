import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


FERNET_PREFIX = "fernet:"


def encrypt_text(value: str) -> str:
    if not value or is_encrypted(value):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{FERNET_PREFIX}{token}"


def decrypt_text(value: str) -> str:
    if not value:
        return ""
    if not is_encrypted(value):
        return value
    token = value.removeprefix(FERNET_PREFIX).encode("ascii")
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Encrypted value cannot be decrypted with the configured key.") from exc


def is_encrypted(value: str) -> bool:
    return value.startswith(FERNET_PREFIX)


def _fernet() -> Fernet:
    key = getattr(settings, "GMAIL_OAUTH_TOKEN_FERNET_KEY", "").strip()
    if not key:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(key.encode("ascii"))
