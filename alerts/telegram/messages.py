import asyncio
import html
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from ..health import build_health_report
from ..gmail_polling import GmailPollingStatus, get_gmail_polling_status
from ..models import MailboxAccount, MarketplaceAlert
from .i18n import use_argus_telegram_language
from .quiet_hours import quiet_hours_allows_alert

TELEGRAM_HARD_MESSAGE_LIMIT = 4096
TELEGRAM_SAFE_MESSAGE_LIMIT = 4000
ALERT_REASON_LIMIT = 260
ALERT_MESSAGE_BODY_LIMIT = 1200
SYSTEM_DETAILS_LIMIT = 1200
STATUS_TITLE_LIMIT = 70
REMINDER_REPORT_CASE_LIMIT = 12
REMINDER_REPORT_TITLE_LIMIT = 70


def should_send_telegram_for_alert(alert: MarketplaceAlert, at_time=None) -> bool:
    if alert.event_type == MarketplaceAlert.EventType.NOISE:
        return False
    return quiet_hours_allows_alert(alert, at_time=at_time)


@use_argus_telegram_language
def build_alert_message(alert: MarketplaceAlert) -> str:
    title = alert.listing_title or alert.subject or alert.get_event_type_display()
    buyer = alert.buyer_name or _("Unknown")
    message = alert.message_text or alert.normalized_body or alert.raw_body or _("Text not found")
    flags = _alert_flag_names(alert)
    event_time = alert.received_at or alert.created_at
    mailbox_label = _alert_mailbox_label(alert)
    taken_by = _alert_taken_by_label(alert)

    lines = [
        _build_alert_header(alert),
        f"📬 <b>{_('Mailbox')}:</b> {html.escape(mailbox_label)}",
        f"📅 <b>{_('Date')}:</b> {_format_date_from_datetime(event_time)}",
        f"🕒 <b>{_('Time')}:</b> {_format_time(event_time)}",
        f"🆔 <b>ID:</b> {alert.id}",
        f"📌 <b>{_('Status')}:</b> {html.escape(alert.get_alert_status_display())}",
    ]
    if taken_by:
        lines.append(f"👷 <b>{_('In work by')}:</b> {html.escape(taken_by)}")
    if alert.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        lines.append(f"👤 <b>{_('Buyer')}:</b> {html.escape(buyer)}")
    lines.extend(
        [
            f"🚗 <b>{_('Listing')}:</b> {html.escape(title)}",
            f"{_priority_emoji(alert)} <b>{_('Priority')}:</b> {html.escape(alert.get_priority_display())}",
            f"🏷️ <b>{_('Type')}:</b> {html.escape(alert.get_event_type_display())}",
            f"🚩 <b>{_('Flags')}:</b> {html.escape(flags)}",
        ]
    )
    if alert.classification_reason:
        reason = html.escape(_truncate(alert.classification_reason, ALERT_REASON_LIMIT))
        lines.append(f"🧾 <b>{_('Reason')}:</b> {reason}")
    lines.extend(
        [
            "",
            f"💬 {html.escape(_truncate(message, ALERT_MESSAGE_BODY_LIMIT))}",
        ]
    )
    return _fit_telegram_message(lines)


@use_argus_telegram_language
def build_alert_reminder_message(alert: MarketplaceAlert) -> str:
    event_time = alert.received_at or alert.created_at
    return _fit_telegram_message(
        [
            _("⏰ <b>Argus: unread lead reminder</b>"),
            f"📅 <b>{_('Date')}:</b> {_format_date_from_datetime(event_time)}",
            f"🕒 <b>{_('Time')}:</b> {_format_time(event_time)}",
            f"🟠 <b>{_('Status')}:</b> {_('needs attention')}",
            "",
            build_alert_message(alert),
        ]
    )


@use_argus_telegram_language
def build_unread_reminder_report_message(alerts) -> str:
    alerts = list(alerts)
    now = timezone.now()
    cases = _group_unread_reminder_cases(alerts)
    high_total = sum(case["high_count"] for case in cases)
    oldest_minutes = 0
    if cases:
        oldest = min(case["oldest"].created_at for case in cases)
        oldest_minutes = max(int((now - oldest).total_seconds() // 60), 0)
    report_icon = "🔴" if high_total else "🟠" if alerts else "🟢"

    lines = [
        _("⏰ <b>Argus: unread leads</b>"),
        f"📅 <b>{_('Date')}:</b> {_format_date(timezone.localdate())}",
        f"🕒 <b>{_('Time')}:</b> {_format_time(now)}",
        "",
        f"{report_icon} <b>{_('Status')}:</b> {_('needs attention')}",
        f"🆕 <b>{_('Unread')}:</b> {len(alerts)}",
        f"📂 <b>{_('Cases')}:</b> {len(cases)}",
        f"🔥 <b>High/Urgent:</b> {high_total}",
        f"⏳ <b>{_('Oldest')}:</b> {_format_age_minutes(oldest_minutes)}",
        "",
    ]

    if not alerts:
        lines.append(_("🟢 There are no unread leads for reminder."))
        return _fit_telegram_message(lines)

    for index, case in enumerate(cases[:REMINDER_REPORT_CASE_LIMIT], start=1):
        latest = case["latest"]
        oldest = case["oldest"]
        age_minutes = max(int((now - oldest.created_at).total_seconds() // 60), 0)
        led = "🔴" if case["high_count"] else "🟠" if age_minutes >= 60 else "🔵"
        title = _truncate(
            latest.listing_title or latest.subject or latest.get_event_type_display(),
            REMINDER_REPORT_TITLE_LIMIT,
        )
        buyer = _latest_known_buyer_name(case["alerts"])
        mailbox_label = _alert_mailbox_label(latest)
        lines.extend(
            [
                f"{led} <b>{index}. {html.escape(title)}</b>",
                (
                    f"🆕 {case['count']} {_('unread')} · "
                    f"🔥 {case['high_count']} high · "
                    f"⏳ {_format_age_minutes(age_minutes)}"
                ),
                f"👤 <b>{_('Latest')}:</b> {html.escape(buyer)}",
                f"📬 <b>{_('Mailbox')}:</b> {html.escape(mailbox_label)}",
                "",
            ]
        )

    hidden_cases = len(cases) - REMINDER_REPORT_CASE_LIMIT
    if hidden_cases > 0:
        lines.append(_("…and %(count)s more cases.") % {"count": hidden_cases})
        lines.append("")

    return _fit_telegram_message(lines)


def _group_unread_reminder_cases(alerts: list[MarketplaceAlert]) -> list[dict]:
    grouped = {}
    for alert in alerts:
        key = (alert.mailbox_id, alert.listing_id or alert.listing_title or alert.subject or alert.id)
        item = grouped.setdefault(
            key,
            {
                "count": 0,
                "high_count": 0,
                "latest": alert,
                "oldest": alert,
                "alerts": [],
            },
        )
        item["count"] += 1
        item["alerts"].append(alert)
        if alert.priority in [MarketplaceAlert.Priority.HIGH, MarketplaceAlert.Priority.URGENT]:
            item["high_count"] += 1
        if alert.created_at > item["latest"].created_at:
            item["latest"] = alert
        if alert.created_at < item["oldest"].created_at:
            item["oldest"] = alert

    return sorted(
        grouped.values(),
        key=lambda item: (
            -item["high_count"],
            item["oldest"].created_at,
            item["latest"].id,
        ),
    )


def _latest_known_buyer_name(alerts: list[MarketplaceAlert]) -> str:
    ordered_alerts = sorted(alerts, key=lambda alert: (alert.created_at, alert.id), reverse=True)
    for alert in ordered_alerts:
        buyer_name = (alert.buyer_name or "").strip()
        if buyer_name:
            return buyer_name

    for alert in ordered_alerts:
        inferred_name = _infer_buyer_name_for_reminder(alert)
        if inferred_name:
            return inferred_name

    return _("unknown")


def _infer_buyer_name_for_reminder(alert: MarketplaceAlert) -> str:
    text = " ".join(
        [
            alert.subject or "",
            alert.raw_subject or "",
            alert.message_text or "",
            alert.normalized_body or "",
        ]
    ).lower()
    if "nutzer-anfrage zu deiner anzeige" in text:
        return "Interessent"
    if "ein interessent hat eine anfrage zu" in text:
        return "Interessent"
    return ""


def _build_alert_header(alert: MarketplaceAlert) -> str:
    if alert.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        return _("🚨 <b>New lead</b>")

    if alert.event_type == MarketplaceAlert.EventType.LISTING_EXPIRING:
        return _("⏳ <b>Kleinanzeigen: listing is expiring</b>")

    if alert.event_type == MarketplaceAlert.EventType.SYSTEM_NOTICE:
        return _("⚙️ <b>Kleinanzeigen: system notice</b>")

    if alert.event_type == MarketplaceAlert.EventType.NOISE:
        return _("🧹 <b>Kleinanzeigen: noise / promo</b>")

    return "📣 <b>Argus alert</b>"


def _alert_flag_names(alert: MarketplaceAlert) -> str:
    preloaded = getattr(alert, "_telegram_flag_names", None)
    if preloaded is not None:
        return preloaded or _("none")

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return ", ".join(alert.flags.values_list("name", flat=True)) or _("none")

    return _("none")


def _alert_mailbox_label(alert: MarketplaceAlert) -> str:
    preloaded = getattr(alert, "_telegram_mailbox_label", None)
    if preloaded is not None:
        return preloaded or _("Unknown")

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return _("Unknown")

    mailbox = alert.mailbox
    if mailbox.name and mailbox.email:
        return f"{mailbox.name} ({mailbox.email})"
    return mailbox.name or mailbox.email or _("Unknown")


def _alert_taken_by_label(alert: MarketplaceAlert) -> str:
    if alert.taken_by:
        return alert.taken_by.get_full_name() or alert.taken_by.get_username()
    return alert.taken_by_label


@use_argus_telegram_language
def build_system_message(title: str, details: str = "") -> str:
    icon, status = _system_message_status(title, details)
    now = timezone.now()

    lines = [
        _("⚙️ <b>Argus: technical event</b>"),
        f"📅 <b>{_('Date')}:</b> {_format_date(timezone.localdate())}",
        f"🕒 <b>{_('Time')}:</b> {_format_time(now)}",
        "",
        f"{icon} <b>{_('Status')}:</b> {status}",
        f"🧩 <b>{_('Component')}:</b> {html.escape(title)}",
    ]

    if details:
        lines.extend(
            [
                "",
                f"🧾 <b>{_('Details')}:</b> {html.escape(_truncate(details, SYSTEM_DETAILS_LIMIT))}",
            ]
        )

    return _fit_telegram_message(lines)


def _system_message_status(title: str, details: str = "") -> tuple[str, str]:
    text = f"{title} {details}".lower()

    if "error" in text or "failed" in text or "ошибка" in text:
        return "🔴", _("Error")

    if "recovered" in text or "restored" in text or "восстанов" in text:
        return "🟢", _("Recovered")

    if "warning" in text or "partial" in text or "предупреж" in text:
        return "🟠", _("Warning")

    return "🔵", _("Information")


@use_argus_telegram_language
def build_mailbox_status_message() -> str:
    today = timezone.localdate()
    day_start = timezone.make_aware(
        timezone.datetime.combine(today, timezone.datetime.min.time())
    )
    day_end = day_start + timedelta(days=1)

    mailboxes = MailboxAccount.objects.filter(is_active=True).order_by("email")

    lines = [
        _("📡 <b>Argus: mailbox status</b>"),
        f"📅 <b>{_('Date')}:</b> {_format_date(today)}",
        f"🕒 <b>{_('Time')}:</b> {_format_time(timezone.now())}",
        "",
    ]

    if not mailboxes.exists():
        lines.append(_("⚠️ There are no active mailboxes."))
        return _fit_telegram_message(lines)

    for mailbox in mailboxes:
        mailbox_alerts = MarketplaceAlert.objects.filter(mailbox=mailbox)

        today_alerts = mailbox_alerts.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        unread_alerts = mailbox_alerts.filter(
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        ).count()

        in_work_alerts = mailbox_alerts.filter(
            alert_status=MarketplaceAlert.AlertStatus.IN_WORK,
        ).count()

        last_error = mailbox.last_error or _("none")

        lines.extend(
            [
                f"📬 <b>{html.escape(mailbox.name)}</b>",
                f"✉️ Email: <code>{html.escape(mailbox.email)}</code>",
                f"🩺 Health: {_build_mailbox_health_label(mailbox)}",
                f"🔌 {_('Active')}: {_('yes') if mailbox.is_active else _('no')}",
                f"🔐 {_('Connection')}: {html.escape(mailbox.get_connection_status_display())}",
                f"🕒 {_('Last check')}: {_format_dt(mailbox.last_checked_at)}",
                f"✅ {_('Last success')}: {_format_dt(mailbox.last_success_at)}",
                f"⚠️ {_('Error')}: {html.escape(_truncate(last_error, 220))}",
                (
                    "📊 Alerts: "
                    f"{_('today')} {today_alerts}, "
                    f"🆕 {_('new')} {unread_alerts}, "
                    f"🛠️ {_('in work')} {in_work_alerts}"
                ),
                "",
            ]
        )

    return _fit_telegram_message(lines)


@use_argus_telegram_language
def build_daily_summary_message() -> str:
    today = timezone.localdate()

    alerts = MarketplaceAlert.objects.filter(created_at__date=today)
    counts = alerts.aggregate(
        total=Count("id"),
        buyer_messages=Count(
            "id",
            filter=Q(event_type=MarketplaceAlert.EventType.BUYER_MESSAGE),
        ),
        listing_expiring=Count(
            "id",
            filter=Q(event_type=MarketplaceAlert.EventType.LISTING_EXPIRING),
        ),
        system_notice=Count(
            "id",
            filter=Q(event_type=MarketplaceAlert.EventType.SYSTEM_NOTICE),
        ),
        noise=Count(
            "id",
            filter=Q(event_type=MarketplaceAlert.EventType.NOISE),
        ),
        unread=Count(
            "id",
            filter=Q(alert_status=MarketplaceAlert.AlertStatus.UNREAD),
        ),
        in_work=Count(
            "id",
            filter=Q(alert_status=MarketplaceAlert.AlertStatus.IN_WORK),
        ),
        ignored=Count(
            "id",
            filter=Q(alert_status=MarketplaceAlert.AlertStatus.IGNORED),
        ),
        high_priority=Count(
            "id",
            filter=Q(
                priority__in=[
                    MarketplaceAlert.Priority.HIGH,
                    MarketplaceAlert.Priority.URGENT,
                ]
            ),
        ),
        parser_attention=Count(
            "id",
            filter=Q(
                parse_status__in=[
                    MarketplaceAlert.ParseStatus.PARTIAL,
                    MarketplaceAlert.ParseStatus.ERROR,
                ]
            ),
        ),
        telegram_errors=Count(
            "id",
            filter=~Q(telegram_error=""),
        ),
    )

    mailbox_counts = MailboxAccount.objects.aggregate(
        active=Count(
            "id",
            filter=Q(is_active=True),
        ),
        errors=Count(
            "id",
            filter=Q(connection_status=MailboxAccount.ConnectionStatus.ERROR),
        ),
    )

    return _fit_telegram_message(
        [
            _("📊 <b>Argus: daily summary</b>"),
            f"📅 <b>{_('Date')}:</b> {_format_date(today)}",
            f"🕒 <b>{_('Time')}:</b> {_format_time(timezone.now())}",
            "",
            f"📨 <b>{_('Events')}</b>",
            f"📊 <b>{_('Total events today')}:</b> {counts['total']}",
            f"👤 <b>{_('Buyer messages')}:</b> {counts['buyer_messages']}",
            f"⏳ <b>{_('Expiring listings')}:</b> {counts['listing_expiring']}",
            f"⚙️ <b>{_('System notices')}:</b> {counts['system_notice']}",
            f"🧹 <b>{_('Noise')}:</b> {counts['noise']}",
            "",
            f"📌 <b>{_('Workflow')}</b>",
            f"🆕 <b>{_('New')}:</b> {counts['unread']}",
            f"🛠️ <b>{_('In work')}:</b> {counts['in_work']}",
            f"🚫 <b>{_('Ignored')}:</b> {counts['ignored']}",
            f"🔥 <b>{_('High priority')}:</b> {counts['high_priority']}",
            f"⚠️ <b>{_('Parser attention')}:</b> {counts['parser_attention']}",
            f"📤 <b>{_('Telegram send errors')}:</b> {counts['telegram_errors']}",
            "",
            f"📬 <b>{_('Mailboxes')}</b>",
            f"🟢 <b>{_('Active mailboxes')}:</b> {mailbox_counts['active']}",
            f"🔴 <b>{_('Mailbox errors')}:</b> {mailbox_counts['errors']}",
        ]
    )


@use_argus_telegram_language
def build_health_message(bot_started_at=None) -> str:
    report = build_health_report()
    summary = report["summary"]
    checks = report["checks"]
    last_check = summary["mailboxes"]["last_checked_at"]
    last_success = summary["mailboxes"]["last_success_at"]
    unread = summary["alerts"]["unread"]
    today = summary["alerts"]["today"]
    telegram_errors_recent = summary["alerts"].get("telegram_errors_recent", 0)
    open_errors = summary["open_service_errors"]
    uptime = _("unknown")
    if bot_started_at:
        delta = timezone.now() - bot_started_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        uptime = f"{hours}h {minutes}m"
    mobile_url = _build_mobile_url()

    def label(name):
        return "OK" if checks[name]["ok"] else checks[name]["status"].upper()

    def icon(name):
        return "🟢" if checks[name]["ok"] else "🔴" if checks[name]["status"] == "error" else "🟠"

    lines = [
        "🩺 <b>Argus: health</b>",
        f"📅 <b>{_('Date')}:</b> {_format_date(timezone.localdate())}",
        f"🕒 <b>{_('Time')}:</b> {_format_time(timezone.now())}",
        "",
        f"{icon('database')} <b>DB:</b> {html.escape(label('database'))}",
        f"{icon('active_mailbox')} <b>{_('Mailboxes')}:</b> {_('active')} {summary['mailboxes']['active']} / {_('errors')} {summary['mailboxes']['errors']}",
        f"{icon('telegram')} <b>Telegram:</b> {html.escape(label('telegram'))}",
        f"{icon('telegram_delivery')} <b>Telegram delivery:</b> {telegram_errors_recent} {_('errors in 24h')}",
        f"{icon('gmail_recent_check')} <b>Gmail:</b> {html.escape(label('gmail_recent_check'))}",
        f"🕒 <b>{_('Last check')}:</b> {_format_dt(last_check)}",
        f"✅ <b>{_('Last success')}:</b> {_format_dt(last_success)}",
        f"💾 <b>{_('Backups')}:</b> {html.escape(checks['backup']['detail'])}",
        "",
        f"🔴 <b>{_('Open errors')}:</b> {open_errors}",
        f"🆕 <b>{_('New leads')}:</b> {unread}",
        f"📨 <b>{_('Today')}:</b> {today}",
        f"🤖 <b>{_('Bot uptime')}:</b> {html.escape(uptime)}",
    ]
    if mobile_url:
        lines.extend(
            [
                "",
                f'📱 <a href="{html.escape(mobile_url)}">{_("Open mobile admin")}</a>',
            ]
        )
    return _fit_telegram_message(lines)


@use_argus_telegram_language
def build_gmail_polling_message(status: GmailPollingStatus | None = None) -> str:
    status = status or get_gmail_polling_status()
    status_icon = "⚪" if not status.is_available else "🟢" if status.is_enabled else "🔴"
    timer_icon = "⚪" if not status.is_available else "🟢" if status.is_active else "🟠"

    lines = [
        f"📬 <b>Argus: {_('Gmail polling')}</b>",
        f"📅 <b>{_('Date')}:</b> {_format_date(timezone.localdate())}",
        f"🕒 <b>{_('Time')}:</b> {_format_time(timezone.now())}",
        "",
        f"{status_icon} <b>{_('Status')}:</b> {html.escape(status.enabled_label)}",
        f"{timer_icon} <b>{_('Timer')}:</b> {html.escape(status.active_label)}",
        f"⏭ <b>{_('Next run')}:</b> {html.escape(status.localized_next_run_label)}",
        f"⏱ <b>{_('Interval')}:</b> {html.escape(status.localized_interval_label)}",
    ]
    if status.error:
        lines.extend(
            [
                "",
                f"⚠️ <b>{_('Systemd status error')}:</b> {html.escape(_truncate(status.error, 500))}",
            ]
        )
    return _fit_telegram_message(lines)


@use_argus_telegram_language
def _build_status_answer(alert: MarketplaceAlert) -> str:
    title = alert.listing_title or alert.subject or alert.get_event_type_display()

    return (
        f"#{alert.id}: "
        f"{alert.get_alert_status_display()} · "
        f"{alert.get_priority_display()} · "
        f"{_truncate(title, STATUS_TITLE_LIMIT)}"
    )


def _build_mobile_url() -> str:
    base_url = getattr(settings, "ARGUS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/m/"


def _mobile_alert_url(alert: MarketplaceAlert) -> str:
    path = reverse("mobile_alert_detail", args=[alert.id])
    base_url = getattr(settings, "ARGUS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return f"{base_url}{path}"
    return path


def _format_date(value) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y")


def _format_date_from_datetime(value) -> str:
    if value is None:
        return "—"

    return timezone.localtime(value).strftime("%d.%m.%Y")


def _format_time(value) -> str:
    if value is None:
        return "—"

    return timezone.localtime(value).strftime("%H:%M")


def _format_dt(value) -> str:
    if value is None:
        return "—"

    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _format_age_minutes(minutes: int) -> str:
    minutes = max(int(minutes), 0)

    if minutes < 60:
        return _("%(count)s min") % {"count": minutes}

    hours = round(minutes / 60)
    if hours < 24:
        return _("%(count)s h") % {"count": hours}

    days = round(hours / 24)
    return _("%(count)s d") % {"count": days}


def _priority_emoji(alert: MarketplaceAlert) -> str:
    if alert.priority == MarketplaceAlert.Priority.URGENT:
        return "🔴"

    if alert.priority == MarketplaceAlert.Priority.HIGH:
        return "🔥"

    if alert.priority == MarketplaceAlert.Priority.NORMAL:
        return "🔵"

    return "⚪"


def _build_mailbox_health_label(mailbox: MailboxAccount) -> str:
    if mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR:
        return "🔴 ERROR"

    if mailbox.last_error:
        return "🟠 WARNING"

    if mailbox.last_checked_at and mailbox.last_success_at:
        return "🟢 OK"

    if mailbox.gmail_oauth_token:
        return "🟡 OAUTH ONLY"

    return "⚪ NOT READY"


def _fit_telegram_message(lines: list[str], limit: int = TELEGRAM_SAFE_MESSAGE_LIMIT) -> str:
    return _truncate_html_message("\n".join(lines), limit)


def _truncate_html_message(value: str, limit: int = TELEGRAM_SAFE_MESSAGE_LIMIT) -> str:
    value = str(value or "").strip()

    if len(value) <= limit:
        return value

    suffix = "..."
    cut_limit = max(limit - len(suffix), 0)
    candidate = value[:cut_limit].rstrip()
    candidate = _trim_incomplete_html_entity(candidate)
    candidate = _trim_incomplete_html_tag(candidate)

    if not candidate:
        return suffix[:limit]

    return f"{candidate}{suffix}"


def _trim_incomplete_html_entity(value: str) -> str:
    last_ampersand = value.rfind("&")
    last_semicolon = value.rfind(";")

    if last_ampersand > last_semicolon:
        return value[:last_ampersand].rstrip()

    return value


def _trim_incomplete_html_tag(value: str) -> str:
    last_tag_open = value.rfind("<")
    last_tag_close = value.rfind(">")

    if last_tag_open > last_tag_close:
        return value[:last_tag_open].rstrip()

    return value


def _truncate(value: str, limit: int) -> str:
    value = str(value or "").strip()

    if len(value) <= limit:
        return value

    suffix = "..."
    if limit <= len(suffix):
        return value[:limit]

    return f"{value[: limit - len(suffix)]}{suffix}"
