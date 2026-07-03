import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from alerts.gmail.gmail_oauth import (
    OAUTH_CODE_VERIFIER_SESSION_KEY,
    OAUTH_STATE_SESSION_KEY,
    build_gmail_authorization_url,
    complete_gmail_oauth_callback,
)
from alerts.models import MailboxAccount


class FakeCredentials:
    def to_json(self):
        return '{"token": "access-token", "refresh_token": "refresh-token"}'


class FakeFlow:
    last_instance = None

    def __init__(self):
        self.credentials = FakeCredentials()
        self.authorization_kwargs = None
        self.fetch_token_kwargs = None
        FakeFlow.last_instance = self

    @classmethod
    def from_client_secrets_file(cls, credentials_file, scopes, redirect_uri):
        flow = cls()
        flow.credentials_file = credentials_file
        flow.scopes = scopes
        flow.redirect_uri = redirect_uri
        return flow

    def authorization_url(self, **kwargs):
        self.authorization_kwargs = kwargs
        return "https://accounts.google.com/o/oauth2/auth?fake=1", "unused-state"

    def fetch_token(self, **kwargs):
        self.fetch_token_kwargs = kwargs


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.local",
        password="pass",
    )


@pytest.fixture
def mailbox(db):
    return MailboxAccount.objects.create(
        name="Test Gmail",
        email="maxpetrikin@gmail.com",
        is_active=True,
    )


def attach_session(request):
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    return request


@pytest.mark.django_db
def test_build_gmail_authorization_url_stores_state_and_pkce(
    monkeypatch,
    settings,
    tmp_path,
    rf,
    admin_user,
    mailbox,
):
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(credentials_file))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr("alerts.gmail_oauth.Flow", FakeFlow)

    settings.GOOGLE_OAUTH_REDIRECT_URI = (
        "http://127.0.0.1:8000/control/alerts/mailboxaccount/oauth/callback/"
    )

    request = rf.get(f"/control/alerts/mailboxaccount/{mailbox.id}/gmail/connect/")
    request.user = admin_user
    attach_session(request)

    authorization_url = build_gmail_authorization_url(request, mailbox)

    assert authorization_url == "https://accounts.google.com/o/oauth2/auth?fake=1"
    assert request.session[OAUTH_STATE_SESSION_KEY]
    assert request.session[OAUTH_CODE_VERIFIER_SESSION_KEY]

    flow = FakeFlow.last_instance
    assert flow.redirect_uri == settings.GOOGLE_OAUTH_REDIRECT_URI
    assert flow.authorization_kwargs["access_type"] == "offline"
    assert flow.authorization_kwargs["prompt"] == "consent"
    assert flow.authorization_kwargs["code_challenge"]
    assert flow.authorization_kwargs["code_challenge_method"] == "S256"
    assert flow.authorization_kwargs["state"] == request.session[OAUTH_STATE_SESSION_KEY]


@pytest.mark.django_db
def test_complete_gmail_oauth_callback_saves_mailbox_token(
    monkeypatch,
    settings,
    tmp_path,
    rf,
    admin_user,
    mailbox,
):
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(credentials_file))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr("alerts.gmail_oauth.Flow", FakeFlow)
    monkeypatch.setattr("alerts.gmail_oauth.fetch_google_email", lambda credentials: mailbox.email)

    settings.GOOGLE_OAUTH_REDIRECT_URI = (
        "http://127.0.0.1:8000/control/alerts/mailboxaccount/oauth/callback/"
    )

    start_request = rf.get(f"/control/alerts/mailboxaccount/{mailbox.id}/gmail/connect/")
    start_request.user = admin_user
    attach_session(start_request)

    build_gmail_authorization_url(start_request, mailbox)

    callback_request = rf.get(
        "/control/alerts/mailboxaccount/oauth/callback/",
        {
            "state": start_request.session[OAUTH_STATE_SESSION_KEY],
            "code": "google-auth-code",
        },
    )
    callback_request.user = admin_user
    callback_request.session = start_request.session

    result = complete_gmail_oauth_callback(callback_request)

    mailbox.refresh_from_db()

    assert result.mailbox == mailbox
    assert result.google_email == mailbox.email
    assert mailbox.gmail_connected_email == mailbox.email
    assert mailbox.gmail_oauth_token == '{"token": "access-token", "refresh_token": "refresh-token"}'
    assert mailbox.gmail_oauth_connected_at is not None
    assert mailbox.gmail_oauth_error == ""
    assert mailbox.connection_status == MailboxAccount.ConnectionStatus.CONNECTED
    assert mailbox.last_error == ""

    flow = FakeFlow.last_instance
    assert "authorization_response" in flow.fetch_token_kwargs
    assert flow.fetch_token_kwargs["code_verifier"]


@pytest.mark.django_db
def test_complete_gmail_oauth_callback_rejects_invalid_state(
    rf,
    admin_user,
):
    request = rf.get(
        "/control/alerts/mailboxaccount/oauth/callback/",
        {
            "state": "bad-state",
            "code": "google-auth-code",
        },
    )
    request.user = admin_user
    attach_session(request)
    request.session[OAUTH_STATE_SESSION_KEY] = "expected-state"
    request.session[OAUTH_CODE_VERIFIER_SESSION_KEY] = "verifier"

    with pytest.raises(PermissionDenied, match="Invalid Gmail OAuth state"):
        complete_gmail_oauth_callback(request)


@pytest.mark.django_db
def test_complete_gmail_oauth_callback_rejects_missing_code_verifier(
    monkeypatch,
    settings,
    tmp_path,
    rf,
    admin_user,
    mailbox,
):
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(credentials_file))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr("alerts.gmail_oauth.Flow", FakeFlow)

    settings.GOOGLE_OAUTH_REDIRECT_URI = (
        "http://127.0.0.1:8000/control/alerts/mailboxaccount/oauth/callback/"
    )

    start_request = rf.get(f"/control/alerts/mailboxaccount/{mailbox.id}/gmail/connect/")
    start_request.user = admin_user
    attach_session(start_request)

    build_gmail_authorization_url(start_request, mailbox)

    callback_request = rf.get(
        "/control/alerts/mailboxaccount/oauth/callback/",
        {
            "state": start_request.session[OAUTH_STATE_SESSION_KEY],
            "code": "google-auth-code",
        },
    )
    callback_request.user = admin_user
    callback_request.session = start_request.session
    del callback_request.session[OAUTH_CODE_VERIFIER_SESSION_KEY]

    with pytest.raises(PermissionDenied, match="Missing Gmail OAuth code verifier"):
        complete_gmail_oauth_callback(callback_request)


@pytest.mark.django_db
def test_complete_gmail_oauth_callback_rejects_wrong_google_account(
    monkeypatch,
    settings,
    tmp_path,
    rf,
    admin_user,
    mailbox,
):
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(credentials_file))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr("alerts.gmail_oauth.Flow", FakeFlow)
    monkeypatch.setattr("alerts.gmail_oauth.fetch_google_email", lambda credentials: "other@example.com")

    settings.GOOGLE_OAUTH_REDIRECT_URI = (
        "http://127.0.0.1:8000/control/alerts/mailboxaccount/oauth/callback/"
    )

    start_request = rf.get(f"/control/alerts/mailboxaccount/{mailbox.id}/gmail/connect/")
    start_request.user = admin_user
    attach_session(start_request)

    build_gmail_authorization_url(start_request, mailbox)

    callback_request = rf.get(
        "/control/alerts/mailboxaccount/oauth/callback/",
        {
            "state": start_request.session[OAUTH_STATE_SESSION_KEY],
            "code": "google-auth-code",
        },
    )
    callback_request.user = admin_user
    callback_request.session = start_request.session

    with pytest.raises(ValueError, match="Connected Gmail account mismatch"):
        complete_gmail_oauth_callback(callback_request)

    mailbox.refresh_from_db()
    assert mailbox.gmail_oauth_token == ""
    assert mailbox.connection_status == MailboxAccount.ConnectionStatus.NOT_CONNECTED


@pytest.mark.django_db
def test_admin_gmail_disconnect_clears_oauth_fields(admin_client, admin_user, mailbox):
    admin_client.force_login(admin_user)

    mailbox.gmail_connected_email = mailbox.email
    mailbox.gmail_oauth_token = '{"token": "access-token"}'
    mailbox.gmail_oauth_connected_at = timezone.now()
    mailbox.gmail_oauth_last_refresh_at = timezone.now()
    mailbox.gmail_oauth_error = "old error"
    mailbox.connection_status = MailboxAccount.ConnectionStatus.CONNECTED
    mailbox.last_error = "old error"
    mailbox.save()

    url = reverse("admin:alerts_mailboxaccount_gmail_disconnect", args=[mailbox.id])
    response = admin_client.get(url)

    assert response.status_code == 302

    mailbox.refresh_from_db()
    assert mailbox.gmail_connected_email == ""
    assert mailbox.gmail_oauth_token == ""
    assert mailbox.gmail_oauth_connected_at is None
    assert mailbox.gmail_oauth_last_refresh_at is None
    assert mailbox.gmail_oauth_error == ""
    assert mailbox.connection_status == MailboxAccount.ConnectionStatus.NOT_CONNECTED
    assert mailbox.last_error == ""