import logging

from django.utils import timezone

from .models import MailboxAccount, MarketplaceAlert, ServiceEvent


logger = logging.getLogger(__name__)

IMPORTANT_SEVERITIES = {
    ServiceEvent.Severity.WARNING,
    ServiceEvent.Severity.ERROR,
    ServiceEvent.Severity.CRITICAL,
}


def record_service_event(
    *,
    event_type: str,
    severity: str,
    title: str,
    details: str = "",
    source: str = "",
    fingerprint: str = "",
    mailbox: MailboxAccount | None = None,
    alert: MarketplaceAlert | None = None,
    notify: bool = True,
) -> ServiceEvent:
    fingerprint = fingerprint or _build_fingerprint(event_type, source, mailbox, alert, title)
    now = timezone.now()

    event = ServiceEvent.objects.filter(
        event_type=event_type,
        status=ServiceEvent.Status.OPEN,
        fingerprint=fingerprint,
    ).first()

    if event:
        event.occurrences += 1
        event.last_seen_at = now
        event.details = details or event.details
        event.severity = severity
        event.title = title
        event.save(
            update_fields=[
                "occurrences",
                "last_seen_at",
                "details",
                "severity",
                "title",
                "updated_at",
            ]
        )
        return event

    event = ServiceEvent.objects.create(
        event_type=event_type,
        severity=severity,
        status=ServiceEvent.Status.OPEN,
        source=source,
        title=title,
        details=details,
        fingerprint=fingerprint,
        mailbox=mailbox,
        alert=alert,
        first_seen_at=now,
        last_seen_at=now,
    )

    if notify and severity in IMPORTANT_SEVERITIES:
        _send_service_event_to_telegram(event)

    return event


def record_mailbox_error(mailbox: MailboxAccount, error: Exception | str) -> ServiceEvent:
    return record_service_event(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        title=f"Mailbox error: {mailbox.email}",
        details=str(error),
        source="gmail.check_mailbox",
        fingerprint=_mailbox_fingerprint(mailbox),
        mailbox=mailbox,
    )


def record_parser_error(alert: MarketplaceAlert) -> ServiceEvent | None:
    if alert.parse_status not in {
        MarketplaceAlert.ParseStatus.PARTIAL,
        MarketplaceAlert.ParseStatus.ERROR,
    }:
        return None

    severity = (
        ServiceEvent.Severity.ERROR
        if alert.parse_status == MarketplaceAlert.ParseStatus.ERROR
        else ServiceEvent.Severity.WARNING
    )
    details = alert.parse_error or "Parser did not extract all expected fields."

    return record_service_event(
        event_type=ServiceEvent.EventType.PARSER_ERROR,
        severity=severity,
        title=f"Parser {alert.get_parse_status_display()}: alert #{alert.id}",
        details=details,
        source="parser",
        fingerprint=f"parser:{alert.mailbox_id}:{alert.parse_status}:{details}",
        mailbox=alert.mailbox,
        alert=alert,
    )


def record_telegram_send_error(alert: MarketplaceAlert, error: Exception | str) -> ServiceEvent:
    return record_service_event(
        event_type=ServiceEvent.EventType.TELEGRAM_SEND_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        title=f"Telegram send error: alert #{alert.id}",
        details=str(error),
        source="telegram.sender",
        fingerprint=f"telegram_send:{alert.id}",
        mailbox=alert.mailbox,
        alert=alert,
        notify=False,
    )


async def async_record_telegram_send_error(alert: MarketplaceAlert, error: Exception | str) -> ServiceEvent:
    fingerprint = f"telegram_send:{alert.id}"
    now = timezone.now()
    event = await ServiceEvent.objects.filter(
        event_type=ServiceEvent.EventType.TELEGRAM_SEND_ERROR,
        status=ServiceEvent.Status.OPEN,
        fingerprint=fingerprint,
    ).afirst()

    if event:
        event.occurrences += 1
        event.last_seen_at = now
        event.details = str(error)
        await event.asave(update_fields=["occurrences", "last_seen_at", "details", "updated_at"])
        return event

    return await ServiceEvent.objects.acreate(
        event_type=ServiceEvent.EventType.TELEGRAM_SEND_ERROR,
        severity=ServiceEvent.Severity.ERROR,
        status=ServiceEvent.Status.OPEN,
        source="telegram.sender",
        title=f"Telegram send error: alert #{alert.id}",
        details=str(error),
        fingerprint=fingerprint,
        mailbox_id=alert.mailbox_id,
        alert_id=alert.id,
        first_seen_at=now,
        last_seen_at=now,
    )


def record_mailbox_recovery(mailbox: MailboxAccount, previous_error: str = "") -> ServiceEvent | None:
    open_events = ServiceEvent.objects.filter(
        event_type=ServiceEvent.EventType.MAILBOX_ERROR,
        status=ServiceEvent.Status.OPEN,
        fingerprint=_mailbox_fingerprint(mailbox),
    )
    if not open_events.exists():
        return None

    now = timezone.now()
    open_events.update(
        status=ServiceEvent.Status.RECOVERED,
        resolved_at=now,
        updated_at=now,
    )

    event = ServiceEvent.objects.create(
        event_type=ServiceEvent.EventType.RECOVERY,
        severity=ServiceEvent.Severity.INFO,
        status=ServiceEvent.Status.RECOVERED,
        source="gmail.check_mailbox",
        title=f"Mailbox recovered: {mailbox.email}",
        details=previous_error,
        fingerprint=f"recovery:{_mailbox_fingerprint(mailbox)}:{now.isoformat()}",
        mailbox=mailbox,
        first_seen_at=now,
        last_seen_at=now,
        resolved_at=now,
    )
    _send_service_event_to_telegram(event)
    return event


def _send_service_event_to_telegram(event: ServiceEvent) -> None:
    from .telegram.config import get_telegram_config

    config = get_telegram_config()
    if not config.bot_token or not config.default_chat_id:
        event.telegram_error = "Telegram is not configured for service health alerts."
        event.save(update_fields=["telegram_error", "updated_at"])
        return

    from .telegram.sender import send_system_telegram_alert

    try:
        send_system_telegram_alert(event.title, details=_build_event_details(event))
    except Exception as exc:
        event.telegram_error = str(exc)
        event.save(update_fields=["telegram_error", "updated_at"])
        logger.exception("Service health Telegram send failed. event_id=%s", event.id)
        return

    event.telegram_sent_at = timezone.now()
    event.telegram_error = ""
    event.save(update_fields=["telegram_sent_at", "telegram_error", "updated_at"])


def _build_event_details(event: ServiceEvent) -> str:
    parts = []
    if event.mailbox_id:
        parts.append(f"Mailbox: {event.mailbox.email}")
    if event.alert_id:
        parts.append(f"Alert: #{event.alert_id}")
    if event.details:
        parts.append(event.details)
    if event.occurrences > 1:
        parts.append(f"Occurrences: {event.occurrences}")
    return "\n".join(parts)


def _build_fingerprint(
    event_type: str,
    source: str,
    mailbox: MailboxAccount | None,
    alert: MarketplaceAlert | None,
    title: str,
) -> str:
    mailbox_key = mailbox.id if mailbox else "none"
    alert_key = alert.id if alert else "none"
    return f"{event_type}:{source}:{mailbox_key}:{alert_key}:{title}"


def _mailbox_fingerprint(mailbox: MailboxAccount) -> str:
    return f"mailbox:{mailbox.id}:gmail_check"
