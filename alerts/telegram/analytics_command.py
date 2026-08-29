from asgiref.sync import sync_to_async

from .i18n import telegram_gettext
from .messages import build_apps_analytics_message
from .permissions import is_allowed_update

PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."


async def handle_analytics_command(update, context):
    """Show only saved Kleinanzeigen view analytics."""
    if not is_allowed_update(update):
        await update.effective_message.reply_text(
            telegram_gettext(PERMISSION_DENIED_MESSAGE)
        )
        return

    analytics_text = await sync_to_async(
        build_apps_analytics_message,
        thread_sensitive=True,
    )()

    if not analytics_text:
        analytics_text = "📊 Аналитика\n\nСтатистика просмотров пока недоступна."

    await update.effective_message.reply_text(
        analytics_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
