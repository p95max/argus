import asyncio
from contextlib import contextmanager
import logging
import os

from django.utils import timezone
from telegram import Bot

from ..models import MarketplaceAlert
from .config import get_telegram_config
from .keyboards import build_alert_keyboard
from .messages import build_alert_message, build_system_message
from .permissions import is_allowed_chat


logger = logging.getLogger(__name__)


def send_telegram_alert(
    alert: MarketplaceAlert,
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    alert._telegram_flag_names = ", ".join(alert.flags.values_list("name", flat=True))
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

    logger.info(
        "Telegram alert send requested. alert_id=%s target_chat_id=%s",
        alert.id,
        target_chat_id or "empty",
    )

    if not target_chat_id:
        logger.error(
            "Telegram alert send failed: TELEGRAM_DEFAULT_CHAT_ID is not configured. alert_id=%s",
            alert.id,
        )
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")

    if not is_allowed_chat(target_chat_id):
        logger.warning(
            "Telegram alert send rejected: chat is not allowed. alert_id=%s target_chat_id=%s",
            alert.id,
            target_chat_id,
        )
        raise PermissionError("Telegram chat is not allowed.")

    if bot is None:
        if not config.bot_token:
            logger.error(
                "Telegram alert send failed: TELEGRAM_BOT_TOKEN is not configured. alert_id=%s",
                alert.id,
            )
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")

        bot = Bot(token=config.bot_token)

    text = build_alert_message(alert)
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
        error = str(exc)
        alert.telegram_error = error
        with _allow_async_unsafe_orm():
            alert.save(
                update_fields=[
                    "telegram_error",
                    "updated_at",
                ]
            )
        from ..service_health import record_telegram_send_error

        with _allow_async_unsafe_orm():
            record_telegram_send_error(alert, exc)

        logger.exception(
            "Telegram alert send failed. alert_id=%s target_chat_id=%s",
            alert.id,
            target_chat_id,
        )
        raise

    alert.telegram_chat_id = target_chat_id
    alert.telegram_message_id = str(getattr(message, "message_id", ""))
    alert.telegram_sent_at = timezone.now()
    alert.telegram_error = ""

    with _allow_async_unsafe_orm():
        alert.save(
            update_fields=[
                "telegram_chat_id",
                "telegram_message_id",
                "telegram_sent_at",
                "telegram_error",
                "updated_at",
            ]
        )

    logger.info(
        "Telegram alert sent. alert_id=%s target_chat_id=%s telegram_message_id=%s",
        alert.id,
        target_chat_id,
        alert.telegram_message_id,
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

    logger.info(
        "Telegram system message send requested. title=%s target_chat_id=%s",
        title,
        target_chat_id or "empty",
    )

    if not target_chat_id:
        logger.error(
            "Telegram system message send failed: TELEGRAM_DEFAULT_CHAT_ID is not configured. title=%s",
            title,
        )
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")

    if not is_allowed_chat(target_chat_id):
        logger.warning(
            "Telegram system message send rejected: chat is not allowed. title=%s target_chat_id=%s",
            title,
            target_chat_id,
        )
        raise PermissionError("Telegram chat is not allowed.")

    if bot is None:
        if not config.bot_token:
            logger.error(
                "Telegram system message send failed: TELEGRAM_BOT_TOKEN is not configured. title=%s",
                title,
            )
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")

        bot = Bot(token=config.bot_token)

    try:
        message = await bot.send_message(
            chat_id=target_chat_id,
            text=build_system_message(title, details),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception(
            "Telegram system message send failed. title=%s target_chat_id=%s",
            title,
            target_chat_id,
        )
        raise

    logger.info(
        "Telegram system message sent. title=%s target_chat_id=%s telegram_message_id=%s",
        title,
        target_chat_id,
        getattr(message, "message_id", ""),
    )

    return message


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


@contextmanager
def _allow_async_unsafe_orm():
    previous = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous
