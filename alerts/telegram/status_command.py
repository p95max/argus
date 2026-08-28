import html
from collections import OrderedDict

from django.utils import timezone
from django.utils.translation import gettext as _

from ..mobile_listings import LISTING_CLOSED_MARKER, _build_listing_group_keys
from ..models import MailboxAccount, MarketplaceAlert
from .i18n import use_argus_telegram_language
from .permissions import is_allowed_update

PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."
STATUS_LISTING_LIMIT = 12
STATUS_TITLE_LIMIT = 52


async def handle_status_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(PERMISSION_DENIED_MESSAGE)
        return

    from .handlers import _run_db_sync

    text = await _run_db_sync(build_status_message)
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@use_argus_telegram_language
def build_status_message() -> str:
    sections = [
        _build_compact_mailbox_status(),
        _build_active_listing_status(),
    ]
    return "\n\n".join(section for section in sections if section)


def _build_compact_mailbox_status() -> str:
    mailboxes = list(MailboxAccount.objects.filter(is_active=True).order_by("email"))
    lines = [f"📬 <b>{html.escape(str(_('Mailbox status')))}</b>"]

    if not mailboxes:
        lines.append("⚠️ " + html.escape(str(_("No mailboxes"))))
        return "\n".join(lines)

    for mailbox in mailboxes:
        is_error = (
            mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR
            or bool(mailbox.last_error)
        )
        is_connected = mailbox.connection_status == MailboxAccount.ConnectionStatus.CONNECTED
        icon = "🔴" if is_error else "🟢" if is_connected else "🟠"
        label = mailbox.name or mailbox.email or "—"
        last_check = _format_time(mailbox.last_checked_at)
        lines.append(f"{icon} {html.escape(label)} · {last_check}")

    return "\n".join(lines)


def _build_active_listing_status() -> str:
    alerts = list(
        MarketplaceAlert.objects.filter(event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
        .select_related("mailbox")
        .order_by("-received_at", "-created_at", "-id")
    )
    group_keys = _build_listing_group_keys(alerts)

    grouped = OrderedDict()
    for alert in alerts:
        key = group_keys[alert.id]
        group = grouped.setdefault(
            key,
            {
                "title": alert.listing_title or alert.subject or str(_("Listing")),
                "total": 0,
                "unread": 0,
                "in_work": 0,
                "archived": 0,
                "ignored": 0,
                "is_closed": False,
            },
        )
        group["total"] += 1
        if alert.taken_by_label == LISTING_CLOSED_MARKER:
            group["is_closed"] = True
        if alert.alert_status == MarketplaceAlert.AlertStatus.UNREAD:
            group["unread"] += 1
        elif alert.alert_status == MarketplaceAlert.AlertStatus.IN_WORK:
            group["in_work"] += 1
        elif alert.alert_status == MarketplaceAlert.AlertStatus.ARCHIVED:
            group["archived"] += 1
        elif alert.alert_status == MarketplaceAlert.AlertStatus.IGNORED:
            group["ignored"] += 1

    active_groups = [group for group in grouped.values() if not group["is_closed"]]
    lines = [f"🚗 <b>{html.escape(str(_('Listing')))}: {len(active_groups)}</b>"]

    if not active_groups:
        lines.append("🟢 0")
        return "\n".join(lines)

    for group in active_groups[:STATUS_LISTING_LIMIT]:
        title = _truncate(group["title"], STATUS_TITLE_LIMIT)
        stats = [f"💬 {group['total']}"]
        if group["unread"]:
            stats.append(f"🆕 {group['unread']}")
        if group["in_work"]:
            stats.append(f"🛠 {group['in_work']}")
        if group["archived"]:
            stats.append(f"📦 {group['archived']}")
        if group["ignored"]:
            stats.append(f"🚫 {group['ignored']}")
        lines.append(f"• {html.escape(title)} · {' · '.join(stats)}")

    hidden = len(active_groups) - STATUS_LISTING_LIMIT
    if hidden > 0:
        lines.append(f"… +{hidden}")

    return "\n".join(lines)


def _format_time(value) -> str:
    if value is None:
        return "—"
    return timezone.localtime(value).strftime("%H:%M")


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
