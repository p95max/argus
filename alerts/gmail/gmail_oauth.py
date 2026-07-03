from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import secrets

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .gmail import GMAIL_SCOPES, gmail_credentials_paths
from ..models import MailboxAccount


OAUTH_STATE_SALT = "argus.gmail.admin.oauth"
OAUTH_STATE_SESSION_KEY = "argus_gmail_oauth_state"
OAUTH_CODE_VERIFIER_SESSION_KEY = "argus_gmail_oauth_code_verifier"


@dataclass(frozen=True)
class GmailOAuthResult:
    mailbox: MailboxAccount
    google_email: str


def build_admin_redirect_uri(request) -> str:
    configured_uri = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if configured_uri:
        return configured_uri

    return request.build_absolute_uri(
        reverse("admin:alerts_mailboxaccount_gmail_oauth_callback")
    )


def build_gmail_authorization_url(request, mailbox: MailboxAccount) -> str:
    credentials_file, _ = gmail_credentials_paths()
    if not credentials_file.exists():
        raise FileNotFoundError(f"Gmail client secrets file not found: {credentials_file}")

    state = signing.dumps(
        {
            "mailbox_id": mailbox.id,
            "user_id": request.user.id,
        },
        salt=OAUTH_STATE_SALT,
    )

    code_verifier = _generate_code_verifier()
    code_challenge = _build_code_challenge(code_verifier)

    request.session[OAUTH_STATE_SESSION_KEY] = state
    request.session[OAUTH_CODE_VERIFIER_SESSION_KEY] = code_verifier
    request.session.modified = True

    flow = Flow.from_client_secrets_file(
        str(credentials_file),
        scopes=GMAIL_SCOPES,
        redirect_uri=build_admin_redirect_uri(request),
    )

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return authorization_url


def complete_gmail_oauth_callback(request) -> GmailOAuthResult:
    state = request.GET.get("state", "")
    expected_state = request.session.pop(OAUTH_STATE_SESSION_KEY, "")
    code_verifier = request.session.pop(OAUTH_CODE_VERIFIER_SESSION_KEY, "")
    request.session.modified = True

    if not state or not expected_state or state != expected_state:
        raise PermissionDenied("Invalid Gmail OAuth state.")

    if not code_verifier:
        raise PermissionDenied("Missing Gmail OAuth code verifier.")

    payload = signing.loads(
        state,
        salt=OAUTH_STATE_SALT,
        max_age=10 * 60,
    )

    if payload.get("user_id") != request.user.id:
        raise PermissionDenied("Gmail OAuth user mismatch.")

    mailbox = MailboxAccount.objects.get(id=payload["mailbox_id"])

    credentials_file, _ = gmail_credentials_paths()
    if not credentials_file.exists():
        raise FileNotFoundError(f"Gmail client secrets file not found: {credentials_file}")

    flow = Flow.from_client_secrets_file(
        str(credentials_file),
        scopes=GMAIL_SCOPES,
        redirect_uri=build_admin_redirect_uri(request),
    )

    flow.fetch_token(
        authorization_response=request.build_absolute_uri(),
        code_verifier=code_verifier,
    )

    credentials = flow.credentials
    google_email = fetch_google_email(credentials)

    if google_email.lower() != mailbox.email.lower():
        raise ValueError(
            f"Connected Gmail account mismatch. Expected {mailbox.email}, got {google_email}."
        )

    mailbox.gmail_connected_email = google_email
    mailbox.gmail_oauth_token = credentials.to_json()
    mailbox.gmail_oauth_connected_at = timezone.now()
    mailbox.gmail_oauth_error = ""
    mailbox.connection_status = MailboxAccount.ConnectionStatus.CONNECTED
    mailbox.last_error = ""
    mailbox.save(
        update_fields=[
            "gmail_connected_email",
            "gmail_oauth_token",
            "gmail_oauth_connected_at",
            "gmail_oauth_error",
            "connection_status",
            "last_error",
            "updated_at",
        ]
    )

    return GmailOAuthResult(mailbox=mailbox, google_email=google_email)


def fetch_google_email(credentials) -> str:
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _build_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")