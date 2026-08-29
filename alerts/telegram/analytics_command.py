import html

from asgiref.sync import sync_to_async
from django.utils import timezone

from ..models import Listing
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


def _build_analytics_message() -> str | None:
    analytics = get_listing_analytics()
    if analytics is None:
        return None

    listings = {
        listing.id: listing
        for listing in Listing.objects.filter(
            id__in=[item.listing_id for item in analytics.listings]
        ).prefetch_related("view_stats")
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
        lines.append(
            f"• просмотров за всё время: {_format_count(item.views_count)} 👁"
        )

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

        last_activity_at = None
        if listing:
            latest_stat = next(iter(listing.view_stats.all()), None)
            if latest_stat is not None:
                last_activity_at = latest_stat.created_at

        if last_activity_at:
            activity_date = timezone.localtime(last_activity_at).date()
            activity_age = max((today - activity_date).days, 0)
            activity_icon = "⚠️ " if activity_age > 7 else "• "
            lines.append(
                f"{activity_icon}последняя активность "
                f"{_days_label(activity_age)} ({_format_date(activity_date)})"
            )
        else:
            lines.append("• последняя активность: данных пока нет")

    return "\n".join(lines)


async def handle_analytics_command(update, context):
    """Show listing views, publication age, and the latest detected view activity."""
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
