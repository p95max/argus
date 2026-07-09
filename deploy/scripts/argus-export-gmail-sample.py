#!/usr/bin/env python3
"""Export raw Gmail samples for parser debugging.

This helper is intended to run on the production VPS where MailboxAccount
OAuth tokens and production environment settings are already available.
It writes raw MIME, HTML, text, normalized text, and parser output files.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import asdict
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from pathlib import Path
from typing import Iterable


DEFAULT_PROJECT_DIR = "/opt/argus"
DEFAULT_OUTPUT_DIR = "/tmp/argus-gmail-samples"
DEFAULT_QUERY = "(kleinanzeigen OR kleinanzeigen.de OR eBay Kleinanzeigen) newer_than:365d"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Gmail raw MIME/HTML/text samples for Argus parser debugging.",
    )
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("PROJECT_DIR", DEFAULT_PROJECT_DIR),
        help=f"Argus project directory. Default: {DEFAULT_PROJECT_DIR}",
    )
    parser.add_argument(
        "--mailbox",
        required=True,
        help="Mailbox email address or numeric MailboxAccount ID.",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"Gmail search query. Default: {DEFAULT_QUERY!r}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum number of Gmail messages to export.",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--message-id",
        default="",
        help="Export a specific Gmail message ID instead of searching.",
    )
    return parser.parse_args()


def setup_django(project_dir: Path) -> None:
    if not project_dir.exists():
        raise SystemExit(f"ERROR: project directory does not exist: {project_dir}")

    sys.path.insert(0, str(project_dir))
    os.chdir(project_dir)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()


def decode_gmail_raw(raw_value: str) -> bytes:
    padded = raw_value + "=" * (-len(raw_value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def load_mailbox(mailbox_value: str):
    from alerts.models import MailboxAccount

    queryset = MailboxAccount.objects.all()
    if mailbox_value.isdigit():
        mailbox = queryset.filter(pk=int(mailbox_value)).first()
    else:
        mailbox = queryset.filter(email=mailbox_value).first()

    if mailbox is None:
        raise SystemExit(f"ERROR: mailbox not found: {mailbox_value}")
    if not mailbox.is_active:
        raise SystemExit(f"ERROR: mailbox is not active: {mailbox.email or mailbox.pk}")
    if not mailbox.gmail_oauth_token:
        raise SystemExit(f"ERROR: mailbox has no Gmail OAuth token: {mailbox.email or mailbox.pk}")
    return mailbox


def execute_gmail_request(request, operation: str):
    from alerts.gmail.gmail import _execute_gmail_request_with_retry

    return _execute_gmail_request_with_retry(request, operation=operation)


def search_message_ids(service, query: str, limit: int) -> list[str]:
    request = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max(1, limit),
    )
    response = execute_gmail_request(request, operation="messages.list")
    return [item["id"] for item in response.get("messages", [])]


def fetch_message(service, message_id: str, *, fmt: str) -> dict:
    request = service.users().messages().get(
        userId="me",
        id=message_id,
        format=fmt,
    )
    return execute_gmail_request(request, operation=f"messages.get:{fmt}:{message_id}")


def iter_text_parts(message: Message, content_type: str) -> Iterable[str]:
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_type() == content_type:
                yield decode_email_part(part)
        return

    if message.get_content_type() == content_type:
        yield decode_email_part(message)


def decode_email_part(part: Message) -> str:
    if isinstance(part, EmailMessage):
        try:
            content = part.get_content()
        except LookupError:
            content = None
        if isinstance(content, str):
            return content

    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""

    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def headers_to_dict(headers: list[dict]) -> dict[str, str]:
    return {item.get("name", "").lower(): item.get("value", "") for item in headers}


def safe_preview(value: str, limit: int = 4000) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    value = value.strip(".-_")
    return (value[:80] or fallback).lower()


def write_text(path: Path, content: str) -> None:
    path.write_text(content or "", encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def export_one(service, message_id: str, out_dir: Path, index: int) -> None:
    from alerts.gmail.gmail import parse_gmail_api_message
    from alerts.parser import parse_kleinanzeigen_email

    raw_payload = fetch_message(service, message_id, fmt="raw")
    full_payload = fetch_message(service, message_id, fmt="full")

    raw_mime = decode_gmail_raw(raw_payload["raw"])
    email_message = BytesParser(policy=policy.default).parsebytes(raw_mime)

    gmail_message = parse_gmail_api_message(full_payload)
    parsed = parse_kleinanzeigen_email(gmail_message.subject, gmail_message.body)

    html_body = "\n\n".join(iter_text_parts(email_message, "text/html")).strip()
    text_body = "\n\n".join(iter_text_parts(email_message, "text/plain")).strip()

    headers = headers_to_dict(full_payload.get("payload", {}).get("headers", []))
    base = f"sample-{index:03d}-{safe_filename(message_id, 'message')}"

    eml_path = out_dir / f"{base}.eml"
    html_path = out_dir / f"{base}.html"
    txt_path = out_dir / f"{base}.txt"
    normalized_path = out_dir / f"{base}.normalized.txt"
    json_path = out_dir / f"{base}.json"

    eml_path.write_bytes(raw_mime)
    write_text(html_path, html_body)
    write_text(txt_path, text_body or gmail_message.body)
    write_text(normalized_path, parsed.normalized_body)

    parsed_data = asdict(parsed)
    metadata = {
        "gmail_message_id": gmail_message.message_id,
        "gmail_thread_id": gmail_message.thread_id,
        "subject": gmail_message.subject,
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "message_id_header": headers.get("message-id", ""),
        "received_at": gmail_message.received_at,
        "snippet": full_payload.get("snippet", ""),
        "files": {
            "eml": str(eml_path),
            "html": str(html_path),
            "txt": str(txt_path),
            "normalized": str(normalized_path),
        },
        "parser": {
            "event_type": parsed_data.get("event_type"),
            "parse_status": parsed_data.get("parse_status"),
            "parse_error": parsed_data.get("parse_error"),
            "listing_title": parsed_data.get("listing_title"),
            "listing_id": parsed_data.get("listing_id"),
            "buyer_name": parsed_data.get("buyer_name"),
            "message_text": parsed_data.get("message_text"),
            "priority": parsed_data.get("priority"),
            "flag_codes": parsed_data.get("flag_codes"),
            "classification_reason": parsed_data.get("classification_reason"),
            "normalized_body_preview": safe_preview(parsed.normalized_body),
        },
    }
    write_json(json_path, metadata)

    print(f"Exported {message_id}")
    print(f"  subject: {gmail_message.subject}")
    print(f"  parser: {parsed.event_type} / {parsed.parse_status} / {parsed.parse_error or '-'}")
    print(f"  eml: {eml_path}")
    print(f"  html: {html_path}")
    print(f"  txt: {txt_path}")
    print(f"  normalized: {normalized_path}")
    print(f"  json: {json_path}")


def main() -> int:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("ERROR: --limit must be >= 1")

    project_dir = Path(args.project_dir).resolve()
    setup_django(project_dir)

    from alerts.gmail.gmail import build_gmail_service

    mailbox = load_mailbox(args.mailbox)
    service = build_gmail_service(mailbox=mailbox)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)

    if args.message_id:
        message_ids = [args.message_id]
    else:
        message_ids = search_message_ids(service, args.query, args.limit)

    if not message_ids:
        print(f"No Gmail messages found for mailbox={mailbox.email} query={args.query!r}")
        return 2

    print(f"Mailbox: {mailbox.email}")
    print(f"Output: {out_dir}")
    if not args.message_id:
        print(f"Query: {args.query}")
    print()

    for index, message_id in enumerate(message_ids[: args.limit], start=1):
        export_one(service, message_id, out_dir, index)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
