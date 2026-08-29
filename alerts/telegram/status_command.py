import html
from collections import OrderedDict

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..gmail_polling import get_gmail_polling_status
from ..services.listing_analytics import get_listing_analytics
from ..views.mobile.listings import LISTING_CLOSED_MARKER, _build_listing_group_keys
from ..models import MailboxAccount, MarketplaceAlert
from .i18n import use_argus_telegram_language
from .permissions import is_allowed_update

PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."
STATUS_LISTING_LIMIT = 12
STATUS_TITLE_LIMIT = 52


async def handle_mailboxes_status_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(PERMISSION_DENIED_MESSAGE)
        return

    from .handlers import _run_db_sync

    text = await _run_db_sync(build_mailboxes_status_message)
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def handle_ads_status_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(PERMISSION_DENIED_MESSAGE)
        return

    from .handlers import _run_db_sync

    text = await _run_db_sync(build_ads_status_message)
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=build_ads_status_keyboard(),
        disable_web_page_preview=True,
    )


@use_argus_telegram_language
def build_mailboxes_status_message() -> str:
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
        lines.append(f"{icon} {html.escape(label)}")

    last_success_at = max(
        (mailbox.last_success_at for mailbox in mailboxes if mailbox.last_success_at),
        default=None,
    )
    polling_status = get_gmail_polling_status()
    interval = polling_status.localized_interval_label or "—"

    lines.extend(
        [
            "",
            f"✅ Последняя успешная синхронизация: {_format_time(last_success_at)}",
            f"⏱ Текущий интервал: {html.escape(interval)}",
        ]
    )

    return "\n".join(lines)


@use_argus_telegram_language
def build_ads_status_message() -> str:
    alerts = list(
        MarketplaceAlert.objects.filter(event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
        .select_related("mailbox")
        .order_by("-received_at", "-created_at", "-id")
    )
    group_keys = _build_listing_group_keys(alerts)

    analytics = get_listing_analytics()
    analytics_urls = {}
    if analytics is not None:
        analytics_listing_ids = [item.listing_id for item in analytics.listings]
        from ..models import Listing

        analytics_urls = {
            listing.title.casefold(): listing.kleinanzeigen_url
            for listing in Listing.objects.filter(id__in=analytics_listing_ids)
            if listing.kleinanzeigen_url
        }

    grouped = OrderedDict()
    for alert in alerts:
        key = group_keys[alert.id]
        group = grouped.setdefault(
            key,
            {
                "title": alert.listing_title or alert.subject or str(_("Listing")),
                "total": 0,
                "is_closed": False,
            },
        )
        group["total"] += 1
        if alert.taken_by_label == LISTING_CLOSED_MARKER:
            group["is_closed"] = True

    active_groups = [group for group in grouped.values() if not group["is_closed"]]
    lines = [f"🚗 <b>{html.escape(str(_('Listing')))}: {len(active_groups)}</b>"]

    if not active_groups:
        lines.append("🟢 0")
        return "\n".join(lines)

    for index, group in enumerate(active_groups[:STATUS_LISTING_LIMIT], start=1):
        title = _truncate(group["title"], STATUS_TITLE_LIMIT)
        listing_url = analytics_urls.get(str(group["title"]).casefold())
        link = (
            f' · <a href="{html.escape(listing_url, quote=True)}">ссылка</a>'
            if listing_url
            else ""
        )
        lines.extend(
            [
                "",
                f"{index}. {html.escape(title)}{link}",
                f"· Всего обращений: 💬 {group['total']}",
            ]
        )

    hidden = len(active_groups) - STATUS_LISTING_LIMIT
    if hidden > 0:
        lines.append(f"… +{hidden}")

    return "\n".join(lines)


def build_ads_status_keyboard():
    url = _build_mobile_listings_url()
    if not url:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="🚗 Объявления", url=url)]]
    )


def _build_mobile_listings_url() -> str:
    base_url = getattr(settings, "ARGUS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}{reverse('mobile_listings')}"


def _format_time(value) -> str:
    if value is None:
        return "—"
    return timezone.localtime(value).strftime("%H:%M")


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
