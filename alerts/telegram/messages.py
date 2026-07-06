from datetime import timedelta

import asyncio
import html

from django.db.models import Count, Q
from django.utils import timezone

from ..models import MailboxAccount, MarketplaceAlert
from .quiet_hours import quiet_hours_allows_alert


def should_send_telegram_for_alert(alert: MarketplaceAlert, at_time=None) -> bool:
    if alert.event_type == MarketplaceAlert.EventType.NOISE:
        return False
    return quiet_hours_allows_alert(alert, at_time=at_time)


def build_alert_message(alert: MarketplaceAlert) -> str:
    title = alert.listing_title or alert.subject or alert.get_event_type_display()
    buyer = alert.buyer_name or "Неизвестно"
    message = alert.message_text or alert.normalized_body or alert.raw_body or "Текст не найден"
    flags = _alert_flag_names(alert)
    event_time = alert.received_at or alert.created_at
    mailbox_label = _alert_mailbox_label(alert)

    lines = [
        _build_alert_header(alert),
        f"📬 <b>Ящик:</b> {html.escape(mailbox_label)}",
        f"📅 <b>Дата:</b> {_format_date_from_datetime(event_time)}",
        f"🕒 <b>Время:</b> {_format_time(event_time)}",
        f"🆔 <b>ID:</b> {alert.id}",
        f"📌 <b>Статус:</b> {html.escape(alert.get_alert_status_display())}",
    ]
    if alert.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        lines.append(f"👤 <b>Покупатель:</b> {html.escape(buyer)}")
    lines.extend(
        [
            f"🚗 <b>Объявление:</b> {html.escape(title)}",
            f"{_priority_emoji(alert)} <b>Приоритет:</b> {html.escape(alert.get_priority_display())}",
            f"🏷️ <b>Тип:</b> {html.escape(alert.get_event_type_display())}",
            f"🚩 <b>Флаги:</b> {html.escape(flags)}",
            "",
            f"💬 {html.escape(_truncate(message, 1200))}",
        ]
    )
    return "\n".join(lines)


def build_alert_reminder_message(alert: MarketplaceAlert) -> str:
    return "\n".join(
        [
            "⏰ <b>Reminder: alert всё ещё unread</b>",
            "",
            build_alert_message(alert),
        ]
    )


def _build_alert_header(alert: MarketplaceAlert) -> str:
    if alert.event_type == MarketplaceAlert.EventType.BUYER_MESSAGE:
        return "🚨 <b>Новое обращение</b>"

    if alert.event_type == MarketplaceAlert.EventType.LISTING_EXPIRING:
        return "⏳ <b>Kleinanzeigen: объявление истекает</b>"

    if alert.event_type == MarketplaceAlert.EventType.SYSTEM_NOTICE:
        return "⚙️ <b>Kleinanzeigen: системное уведомление</b>"

    if alert.event_type == MarketplaceAlert.EventType.NOISE:
        return "🧹 <b>Kleinanzeigen: noise / промо</b>"

    return "📣 <b>Argus alert</b>"


def _alert_flag_names(alert: MarketplaceAlert) -> str:
    preloaded = getattr(alert, "_telegram_flag_names", None)
    if preloaded is not None:
        return preloaded or "нет"

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return ", ".join(alert.flags.values_list("name", flat=True)) or "нет"

    return "нет"


def _alert_mailbox_label(alert: MarketplaceAlert) -> str:
    preloaded = getattr(alert, "_telegram_mailbox_label", None)
    if preloaded is not None:
        return preloaded or "Неизвестно"

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return "Неизвестно"

    mailbox = alert.mailbox
    if mailbox.name and mailbox.email:
        return f"{mailbox.name} ({mailbox.email})"
    return mailbox.name or mailbox.email or "Неизвестно"


def build_system_message(title: str, details: str = "") -> str:
    icon = _system_message_icon(title, details)

    lines = [
        f"{icon} <b>Argus: системное уведомление</b>",
        f"📌 {html.escape(title)}",
    ]

    if details:
        lines.extend(
            [
                "",
                f"🧾 {html.escape(_truncate(details, 1200))}",
            ]
        )

    return "\n".join(lines)


def _system_message_icon(title: str, details: str = "") -> str:
    text = f"{title} {details}".lower()

    if "error" in text or "failed" in text or "ошибка" in text:
        return "🔴"

    if "recovered" in text or "restored" in text or "восстанов" in text:
        return "🟢"

    if "warning" in text or "partial" in text or "предупреж" in text:
        return "🟠"

    return "⚙️"


def build_mailbox_status_message() -> str:
    today = timezone.localdate()
    day_start = timezone.make_aware(
        timezone.datetime.combine(today, timezone.datetime.min.time())
    )
    day_end = day_start + timedelta(days=1)

    mailboxes = MailboxAccount.objects.filter(is_active=True).order_by("email")

    lines = [
        "📡 <b>Argus: статус ящиков</b>",
        f"📅 <b>Дата:</b> {_format_date(today)}",
        f"🕒 <b>Время:</b> {_format_time(timezone.now())}",
        "",
    ]

    if not mailboxes.exists():
        lines.append("⚠️ Активных ящиков нет.")
        return "\n".join(lines)

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

        last_error = mailbox.last_error or "нет"

        lines.extend(
            [
                f"📬 <b>{html.escape(mailbox.name)}</b>",
                f"✉️ Email: <code>{html.escape(mailbox.email)}</code>",
                f"🩺 Health: {_build_mailbox_health_label(mailbox)}",
                f"🔌 Активен: {'да' if mailbox.is_active else 'нет'}",
                f"🔐 Подключение: {html.escape(mailbox.get_connection_status_display())}",
                f"🕒 Последняя проверка: {_format_dt(mailbox.last_checked_at)}",
                f"✅ Последний успех: {_format_dt(mailbox.last_success_at)}",
                f"⚠️ Ошибка: {html.escape(_truncate(last_error, 220))}",
                (
                    "📊 Alerts: "
                    f"сегодня {today_alerts}, "
                    f"🆕 новые {unread_alerts}, "
                    f"🛠️ в работе {in_work_alerts}"
                ),
                "",
            ]
        )

    return "\n".join(lines).strip()


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

    return "\n".join(
        [
            "<b>Argus: дневная сводка</b>",
            f"📅 <b>Дата:</b> {_format_date(today)}",
            f"🕒 <b>Время:</b> {_format_time(timezone.now())}",
            "",
            f"Всего событий сегодня: {counts['total']}",
            f"Сообщения покупателей: {counts['buyer_messages']}",
            f"Истекающие объявления: {counts['listing_expiring']}",
            f"Системные уведомления: {counts['system_notice']}",
            f"Шум/noise: {counts['noise']}",
            "",
            f"Новые: {counts['unread']}",
            f"В работе: {counts['in_work']}",
            f"Игнор: {counts['ignored']}",
            f"Высокий приоритет: {counts['high_priority']}",
            f"Parser attention: {counts['parser_attention']}",
            "",
            f"Активные ящики: {mailbox_counts['active']}",
            f"Ящики с ошибкой: {mailbox_counts['errors']}",
        ]
    )


def _build_status_answer(alert: MarketplaceAlert) -> str:
    title = alert.listing_title or alert.subject or alert.get_event_type_display()

    return (
        f"#{alert.id}: "
        f"{alert.get_alert_status_display()} · "
        f"{alert.get_priority_display()} · "
        f"{_truncate(title, 70)}"
    )


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


def _truncate(value: str, limit: int) -> str:
    value = str(value or "").strip()

    if len(value) <= limit:
        return value

    return f"{value[: limit - 1]}..."
