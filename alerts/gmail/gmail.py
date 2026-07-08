import base64
import json
import logging
import os
import time

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..crypto import decrypt_text, encrypt_text
from ..models import LeadFlag, MailboxAccount, MarketplaceAlert, ProcessedEmail
from ..parser import parse_kleinanzeigen_email


GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]
GMAIL_API_RETRY_ATTEMPTS = 3
GMAIL_API_RETRY_BASE_SLEEP_SECONDS = 1.0
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str
    subject: str
    body: str
    received_at: object | None = None


@dataclass(frozen=True)
class ProcessedGmailResult:
    created: bool
    duplicate: bool
    alert: MarketplaceAlert | None = None
    processed_email: ProcessedEmail | None = None


@dataclass(frozen=True)
class MailboxCheckResult:
    fetched: int
    created: int
    duplicates: int


def gmail_credentials_paths() -> tuple[Path, Path]:
    credentials_file = os.environ.get("GOOGLE_CLIENT_SECRETS_FILE", "").strip()
    token_file = os.environ.get("GOOGLE_TOKEN_FILE", "").strip()

    if not credentials_file:
        credentials_file = "credentials.json"
    if not token_file:
        token_file = "token.json"

    return Path(credentials_file), Path(token_file)


def build_gmail_service(
    credentials_file: Path | None = None,
    token_file: Path | None = None,
    mailbox: MailboxAccount | None = None,
):
    if mailbox is not None and mailbox.gmail_oauth_token:
        credentials = load_or_refresh_mailbox_credentials(mailbox)
        return build("gmail", "v1", credentials=credentials)

    credentials_file, token_file = _resolve_paths(credentials_file, token_file)
    credentials = load_or_refresh_credentials(credentials_file, token_file)
    return build("gmail", "v1", credentials=credentials)


def connect_gmail(credentials_file: Path | None = None, token_file: Path | None = None, port: int = 0) -> Path:
    credentials_file, token_file = _resolve_paths(credentials_file, token_file)
    if not credentials_file.exists():
        raise FileNotFoundError(f"Gmail client secrets file not found: {credentials_file}")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), GMAIL_SCOPES)
    credentials = flow.run_local_server(port=port)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return token_file


def load_or_refresh_credentials(credentials_file: Path, token_file: Path) -> Credentials:
    if not token_file.exists():
        raise FileNotFoundError(
            f"Gmail token file not found: {token_file}. Run `python manage.py connect_gmail` first."
        )

    credentials = Credentials.from_authorized_user_file(str(token_file), GMAIL_SCOPES)
    if credentials.valid:
        return credentials

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    if not credentials_file.exists():
        raise FileNotFoundError(f"Gmail client secrets file not found: {credentials_file}")
    raise RuntimeError("Gmail credentials are invalid. Run `python manage.py connect_gmail` again.")


def load_or_refresh_mailbox_credentials(mailbox: MailboxAccount) -> Credentials:
    if not mailbox.gmail_oauth_token:
        raise FileNotFoundError(
            f"Gmail OAuth token is not configured for mailbox {mailbox.email}."
        )

    try:
        token_info = json.loads(decrypt_text(mailbox.gmail_oauth_token))
    except (ValueError, json.JSONDecodeError) as exc:
        mailbox.connection_status = MailboxAccount.ConnectionStatus.ERROR
        mailbox.gmail_oauth_error = "Stored Gmail OAuth token cannot be decrypted or is not valid JSON."
        mailbox.last_error = mailbox.gmail_oauth_error
        mailbox.save(
            update_fields=[
                "connection_status",
                "gmail_oauth_error",
                "last_error",
                "updated_at",
            ]
        )
        raise RuntimeError(mailbox.gmail_oauth_error) from exc

    credentials = Credentials.from_authorized_user_info(token_info, GMAIL_SCOPES)
    if credentials.valid:
        return credentials

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        mailbox.gmail_oauth_token = encrypt_text(credentials.to_json())
        mailbox.gmail_oauth_last_refresh_at = timezone.now()
        mailbox.gmail_oauth_error = ""
        mailbox.last_error = ""
        mailbox.save(
            update_fields=[
                "gmail_oauth_token",
                "gmail_oauth_last_refresh_at",
                "gmail_oauth_error",
                "last_error",
                "updated_at",
            ]
        )
        return credentials

    mailbox.connection_status = MailboxAccount.ConnectionStatus.ERROR
    mailbox.gmail_oauth_error = "Gmail OAuth credentials are invalid. Reconnect Gmail from Admin."
    mailbox.last_error = mailbox.gmail_oauth_error
    mailbox.save(
        update_fields=[
            "connection_status",
            "gmail_oauth_error",
            "last_error",
            "updated_at",
        ]
    )
    raise RuntimeError(mailbox.gmail_oauth_error)


def fetch_gmail_messages(service, query: str, max_results: int = 25) -> list[GmailMessage]:
    request = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results,
    )
    response = _execute_gmail_request_with_retry(request, operation="messages.list")
    messages = response.get("messages", [])
    payloads = _fetch_gmail_message_payloads(service, messages)
    return [parse_gmail_api_message(payload) for payload in payloads]


def _fetch_gmail_message_payloads(service, messages: list[dict]) -> list[dict]:
    if not messages:
        return []

    # Gmail can return "Too many concurrent requests for user" when batch requests
    # fan out many users.messages.get calls at once. Fetch sequentially instead.
    return [_fetch_single_gmail_message_payload(service, item["id"]) for item in messages]


def _fetch_single_gmail_message_payload(service, message_id: str) -> dict:
    request = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    )
    return _execute_gmail_request_with_retry(
        request,
        operation=f"messages.get:{message_id}",
    )


def _execute_gmail_request_with_retry(request, operation: str):
    for attempt in range(1, GMAIL_API_RETRY_ATTEMPTS + 1):
        try:
            return request.execute()
        except HttpError as exc:
            if attempt >= GMAIL_API_RETRY_ATTEMPTS or not _is_retryable_gmail_error(exc):
                raise

            sleep_seconds = GMAIL_API_RETRY_BASE_SLEEP_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Gmail API request failed with retryable error. operation=%s attempt=%s/%s sleep=%ss error=%s",
                operation,
                attempt,
                GMAIL_API_RETRY_ATTEMPTS,
                sleep_seconds,
                exc,
            )
            time.sleep(sleep_seconds)

    raise RuntimeError(f"Gmail API request did not complete: {operation}")


def _is_retryable_gmail_error(exc: HttpError) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in {429, 500, 502, 503, 504}:
        return True

    message = str(exc).lower()
    return (
        "ratelimitexceeded" in message
        or "userratelimitexceeded" in message
        or "too many concurrent requests" in message
    )


def parse_gmail_api_message(payload: dict) -> GmailMessage:
    message_id = payload.get("id", "")
    thread_id = payload.get("threadId", "")
    message_payload = payload.get("payload", {})
    headers = _headers_to_dict(message_payload.get("headers", []))
    subject = headers.get("subject", "")
    received_at = _parse_received_at(headers.get("date", ""))
    body = _extract_body(message_payload)

    return GmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        body=body,
        received_at=received_at,
    )


def check_mailbox(
    mailbox: MailboxAccount,
    service=None,
    messages: list[GmailMessage] | None = None,
    max_results: int = 25,
) -> MailboxCheckResult:
    was_in_error = mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR
    previous_error = mailbox.last_error
    mailbox.last_checked_at = timezone.now()
    mailbox.save(update_fields=["last_checked_at", "updated_at"])

    try:
        if messages is None:
            if service is None:
                service = build_gmail_service(mailbox=mailbox)
            messages = fetch_gmail_messages(service, mailbox.gmail_search_query, max_results=max_results)

        created = 0
        duplicates = 0
        for message in messages:
            result = process_gmail_message(mailbox, message)
            if result.duplicate:
                duplicates += 1
            elif result.created:
                created += 1
                _send_telegram_if_enabled(result.alert)

        mailbox.connection_status = MailboxAccount.ConnectionStatus.CONNECTED
        mailbox.last_success_at = timezone.now()
        mailbox.last_error = ""
        mailbox.save(update_fields=["connection_status", "last_success_at", "last_error", "updated_at"])
        if was_in_error:
            from ..service_health import record_mailbox_recovery

            record_mailbox_recovery(mailbox, previous_error=previous_error)
        return MailboxCheckResult(fetched=len(messages), created=created, duplicates=duplicates)
    except Exception as exc:
        mailbox.connection_status = MailboxAccount.ConnectionStatus.ERROR
        mailbox.last_error = str(exc)
        mailbox.save(update_fields=["connection_status", "last_error", "updated_at"])
        from ..service_health import record_mailbox_error

        record_mailbox_error(mailbox, exc)
        raise


@transaction.atomic
def process_gmail_message(mailbox: MailboxAccount, message: GmailMessage) -> ProcessedGmailResult:
    existing = ProcessedEmail.objects.filter(
        mailbox=mailbox,
        gmail_message_id=message.message_id,
    ).first()
    if existing:
        return ProcessedGmailResult(created=False, duplicate=True, processed_email=existing)

    parsed = parse_kleinanzeigen_email(message.subject, message.body)
    alert = MarketplaceAlert.objects.create(
        mailbox=mailbox,
        event_type=parsed.event_type,
        alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        priority=parsed.priority,
        parse_status=parsed.parse_status,
        parse_error=parsed.parse_error,
        classification_reason=parsed.classification_reason,
        listing_id=parsed.listing_id,
        listing_title=parsed.listing_title,
        buyer_name=parsed.buyer_name,
        subject=parsed.subject,
        message_text=parsed.message_text,
        raw_subject=parsed.raw_subject,
        raw_body=parsed.raw_body,
        normalized_body=parsed.normalized_body,
        gmail_message_id=message.message_id,
        gmail_thread_id=message.thread_id,
        received_at=message.received_at,
    )
    if parsed.flag_codes:
        flags = LeadFlag.objects.filter(code__in=parsed.flag_codes, is_active=True)
        alert.flags.set(flags)

    processed_email = ProcessedEmail.objects.create(
        mailbox=mailbox,
        gmail_message_id=message.message_id,
        gmail_thread_id=message.thread_id,
        subject=message.subject,
        received_at=message.received_at,
    )
    if parsed.parse_status in {
        MarketplaceAlert.ParseStatus.PARTIAL,
        MarketplaceAlert.ParseStatus.ERROR,
    }:
        transaction.on_commit(lambda alert_id=alert.id: _record_parser_service_event(alert_id))
    return ProcessedGmailResult(created=True, duplicate=False, alert=alert, processed_email=processed_email)


def _send_telegram_if_enabled(alert: MarketplaceAlert | None) -> None:
    if alert is None:
        return

    from ..telegram.config import get_telegram_config
    from ..telegram.messages import should_send_telegram_for_alert
    from ..telegram.sender import send_telegram_alert

    if not get_telegram_config().send_on_gmail_check or not should_send_telegram_for_alert(alert):
        return

    try:
        send_telegram_alert(alert)
    except Exception:
        logger.exception("Telegram alert send failed for alert %s", alert.id)


def _record_parser_service_event(alert_id: int) -> None:
    from ..service_health import record_parser_error

    try:
        alert = MarketplaceAlert.objects.select_related("mailbox").get(id=alert_id)
    except MarketplaceAlert.DoesNotExist:
        return
    record_parser_error(alert)


def _resolve_paths(credentials_file: Path | None, token_file: Path | None) -> tuple[Path, Path]:
    env_credentials, env_token = gmail_credentials_paths()
    return Path(credentials_file or env_credentials), Path(token_file or env_token)


def _headers_to_dict(headers: list[dict]) -> dict[str, str]:
    return {item.get("name", "").lower(): item.get("value", "") for item in headers}


def _parse_received_at(value: str):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=timezone.get_current_timezone())
    return parsed


def _extract_body(payload: dict) -> str:
    plain_parts = []
    html_parts = []
    _collect_body_parts(payload, plain_parts, html_parts)
    return "\n".join(plain_parts or html_parts).strip()


def _collect_body_parts(payload: dict, plain_parts: list[str], html_parts: list[str]) -> None:
    mime_type = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if data:
        decoded = _decode_body_data(data)
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)

    for part in payload.get("parts", []) or []:
        _collect_body_parts(part, plain_parts, html_parts)


def _decode_body_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
