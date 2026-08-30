import html

from asgiref.sync import sync_to_async
from django.utils import timezone

from ..models import Listing, MarketplaceAlert
from ..services.listing_analytics import get_listing_analytics
from ..services.listing_metadata import fetch_listing_public_metadata
from .i18n import telegram_gettext
from .permissions import is_allowed_update

PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."


def _format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _days_label(days: int) -> str:
    days = max(int(days), 0)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days % 10 == 1 and days % 100 != 11:
        word = "день"
    elif days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word} назад"


def _publication_icon(age_days: int) -> str:
    if age_days <= 7:
        return "🟢"
    if age_days < 14:
        return "🟡"
    return "🔴"


def _period_views_line(icon: str, label: str, value: int | None) -> str:
    if value is None:
        return f"{icon} {label}: данных пока нет"
    return f"{icon} {label}: +{_format_count(value)} 👁"


def _latest_inquiry_at(listing: Listing):
    if not listing.kleinanzeigen_listing_id:
        return None

    alert = (
        MarketplaceAlert.objects.filter(
            event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
            listing_id=listing.kleinanzeigen_listing_id,
        )
        .order_by("-received_at", "-created_at", "-id")
        .only("received_at", "created_at")
        .first()
    )
    if alert is None:
        return None
    return alert.received_at or alert.created_at


def _build_analytics_message() -> str | None:
    analytics = get_listing_analytics()
    if analytics is None:
        return None

    listings = {
        listing.id: listing
        for listing in Listing.objects.filter(
            id__in=[item.listing_id for item in analytics.listings]
        )
    }
    today = timezone.localdate()

    known_deltas = [
        item.views_delta_24h
        for item in analytics.listings
        if item.views_delta_24h is not None
    ]
    leader_delta = max(known_deltas) if known_deltas else None
    leader_used = False

    lines = [
        "📊 <b>Аналитика</b>",
        "",
        f"👁 <b>Общие просмотры:</b> {_format_count(analytics.total_views)}",
    ]
    if analytics.total_delta_24h is not None:
        lines.append(f"📈 <b>За последние 24 ч:</b> +{_format_count(analytics.total_delta_24h)} 👁")
    if analytics.total_delta_7d is not None:
        lines.append(f"📅 <b>За последние 7 дней:</b> +{_format_count(analytics.total_delta_7d)} 👁")

    for item in analytics.listings:
        listing = listings.get(item.listing_id)
        lines.append("")

        is_leader = (
            not leader_used
            and leader_delta is not None
            and item.views_delta_24h == leader_delta
        )
        leader_used = leader_used or is_leader
        prefix = "🔥 " if is_leader else ""
        lines.append(f"{prefix}<b>{html.escape(item.title)}</b>")
        lines.append(f"👁 просмотров за всё время: {_format_count(item.views_count)}")
        lines.append(_period_views_line("📈", "за последние 24 ч", item.views_delta_24h))
        lines.append(_period_views_line("📅", "за последние 7 дней", item.views_delta_7d))

        published_on = None
        if listing and listing.kleinanzeigen_url:
            try:
                metadata = fetch_listing_public_metadata(listing.kleinanzeigen_url)
                published_on = metadata.published_on
            except Exception:
                published_on = None

        if published_on:
            publication_age = max((today - published_on).days, 0)
            lines.append(
                f"{_publication_icon(publication_age)} опубликовано "
                f"{_days_label(publication_age)} ({_format_date(published_on)})"
            )
        else:
            lines.append("⚪ дата публикации недоступна")

        last_inquiry_at = _latest_inquiry_at(listing) if listing else None
        if last_inquiry_at:
            inquiry_date = timezone.localtime(last_inquiry_at).date()
            inquiry_age = max((today - inquiry_date).days, 0)
            inquiry_icon = "⚠️" if inquiry_age > 7 else "🕒"
            lines.append(
                f"{inquiry_icon} последнее обращение "
                f"{_days_label(inquiry_age)} ({_format_date(inquiry_date)})"
            )
        else:
            lines.append("🕒 последнее обращение: данных пока нет")

    return "\n".join(lines)


async def handle_analytics_command(update, context):
    """Show listing views, publication age, and the latest buyer inquiry."""
    if not is_allowed_update(update):
        await update.effective_message.reply_text(
            telegram_gettext(PERMISSION_DENIED_MESSAGE)
        )
        return

    analytics_text = await sync_to_async(
        _build_analytics_message,
        thread_sensitive=True,
    )()

    if not analytics_text:
        analytics_text = "📊 Аналитика\n\nСтатистика просмотров пока недоступна."

    await update.effective_message.reply_text(
        analytics_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
