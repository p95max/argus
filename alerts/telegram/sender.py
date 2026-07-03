import asyncio

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import Bot

from ..models import MarketplaceAlert
from .config import get_telegram_config
from .keyboards import build_alert_keyboard
from .messages import build_alert_message, build_system_message
from .permissions import is_allowed_chat


def send_telegram_alert(
    alert: MarketplaceAlert,
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    return asyncio.run(
        async_send_telegram_alert(
            alert,
            chat_id=chat_id,
            bot=bot,
        )
    )


async def async_send_telegram_alert(
    alert: MarketplaceAlert,
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    config = get_telegram_config()
    target_chat_id = str(chat_id or config.default_chat_id).strip()

    if not target_chat_id:
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")

    if not is_allowed_chat(target_chat_id):
        raise PermissionError("Telegram chat is not allowed.")

    if bot is None:
        if not config.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
        bot = Bot(token=config.bot_token)

    text = await sync_to_async(build_alert_message)(alert)
    reply_markup = build_alert_keyboard(alert)

    try:
        message = await bot.send_message(
            chat_id=target_chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        alert.telegram_error = str(exc)
        await sync_to_async(alert.save)(
            update_fields=[
                "telegram_error",
                "updated_at",
            ]
        )
        raise

    alert.telegram_chat_id = target_chat_id
    alert.telegram_message_id = str(getattr(message, "message_id", ""))
    alert.telegram_sent_at = timezone.now()
    alert.telegram_error = ""

    await sync_to_async(alert.save)(
        update_fields=[
            "telegram_chat_id",
            "telegram_message_id",
            "telegram_sent_at",
            "telegram_error",
            "updated_at",
        ]
    )

    return message


async def send_system_telegram_message(
    title: str,
    details: str = "",
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    config = get_telegram_config()
    target_chat_id = str(chat_id or config.default_chat_id).strip()

    if not target_chat_id:
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")

    if not is_allowed_chat(target_chat_id):
        raise PermissionError("Telegram chat is not allowed.")

    if bot is None:
        if not config.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
        bot = Bot(token=config.bot_token)

    return await bot.send_message(
        chat_id=target_chat_id,
        text=build_system_message(title, details),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def send_system_telegram_alert(
    title: str,
    details: str = "",
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    return asyncio.run(
        send_system_telegram_message(
            title,
            details=details,
            chat_id=chat_id,
            bot=bot,
        )
    )