import asyncio
import logging

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import Bot

from ..models import MarketplaceAlert
from .config import get_telegram_config
from .keyboards import build_alert_keyboard
from .messages import (
    build_alert_message,
    build_alert_reminder_message,
    build_system_message,
    should_send_telegram_for_alert,
)
from .permissions import is_allowed_chat


logger = logging.getLogger(__name__)


def send_telegram_alert(
    alert: MarketplaceAlert,
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    _preload_alert_message_fields(alert)
    return asyncio.run(
        async_send_telegram_alert(
            alert,
            chat_id=chat_id,
            bot=bot,
        )
    )


def send_telegram_reminder(
    alert: MarketplaceAlert,
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    _preload_alert_message_fields(alert)
    return asyncio.run(
        async_send_telegram_reminder(
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
    should_send = await sync_to_async(should_send_telegram_for_alert, thread_sensitive=True)(alert)
    if not should_send:
        logger.info("Telegram alert send skipped by filters. alert_id=%s", alert.id)
        return None

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
        await alert.asave(
            update_fields=[
                "telegram_error",
                "updated_at",
            ]
        )
        from ..service_health import record_telegram_send_error

        await sync_to_async(record_telegram_send_error, thread_sensitive=True)(alert, exc)

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

    await alert.asave(
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


async def async_send_telegram_reminder(
    alert: MarketplaceAlert,
    chat_id: str | None = None,
    bot: Bot | None = None,
):
    should_send = await sync_to_async(should_send_telegram_for_alert, thread_sensitive=True)(alert)
    if not should_send:
        logger.info("Telegram reminder send skipped by filters. alert_id=%s", alert.id)
        return None

    return await _async_send_alert_message(
        alert,
        text=build_alert_reminder_message(alert),
        chat_id=chat_id,
        bot=bot,
        save_fields=("last_reminded_at", "telegram_error"),
    )


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


async def _async_send_alert_message(
    alert: MarketplaceAlert,
    *,
    text: str,
    chat_id: str | None = None,
    bot: Bot | None = None,
    save_fields: tuple[str, ...],
):
    config = get_telegram_config()
    target_chat_id = str(chat_id or config.default_chat_id).strip()

    logger.info(
        "Telegram alert message send requested. alert_id=%s target_chat_id=%s",
        alert.id,
        target_chat_id or "empty",
    )

    if not target_chat_id:
        logger.error(
            "Telegram alert message send failed: TELEGRAM_DEFAULT_CHAT_ID is not configured. alert_id=%s",
            alert.id,
        )
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")

    if not is_allowed_chat(target_chat_id):
        logger.warning(
            "Telegram alert message send rejected: chat is not allowed. alert_id=%s target_chat_id=%s",
            alert.id,
            target_chat_id,
        )
        raise PermissionError("Telegram chat is not allowed.")

    if bot is None:
        if not config.bot_token:
            logger.error(
                "Telegram alert message send failed: TELEGRAM_BOT_TOKEN is not configured. alert_id=%s",
                alert.id,
            )
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")

        bot = Bot(token=config.bot_token)

    try:
        message = await bot.send_message(
            chat_id=target_chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=build_alert_keyboard(alert),
            disable_web_page_preview=True,
        )
    except Exception as exc:
        error = str(exc)
        alert.telegram_error = error
        await alert.asave(update_fields=["telegram_error", "updated_at"])
        from ..service_health import record_telegram_send_error

        await sync_to_async(record_telegram_send_error, thread_sensitive=True)(alert, exc)

        logger.exception(
            "Telegram alert message send failed. alert_id=%s target_chat_id=%s",
            alert.id,
            target_chat_id,
        )
        raise

    now = timezone.now()
    alert.telegram_error = ""
    if "telegram_chat_id" in save_fields:
        alert.telegram_chat_id = target_chat_id
    if "telegram_message_id" in save_fields:
        alert.telegram_message_id = str(getattr(message, "message_id", ""))
    if "telegram_sent_at" in save_fields:
        alert.telegram_sent_at = now
    if "last_reminded_at" in save_fields:
        alert.last_reminded_at = now

    await alert.asave(update_fields=[*save_fields, "updated_at"])

    logger.info(
        "Telegram alert message sent. alert_id=%s target_chat_id=%s telegram_message_id=%s",
        alert.id,
        target_chat_id,
        getattr(message, "message_id", ""),
    )

    return message


def _preload_alert_message_fields(alert: MarketplaceAlert) -> None:
    alert._telegram_flag_names = ", ".join(alert.flags.values_list("name", flat=True))
    mailbox = alert.mailbox
    if mailbox.name and mailbox.email:
        alert._telegram_mailbox_label = f"{mailbox.name} ({mailbox.email})"
    else:
        alert._telegram_mailbox_label = mailbox.name or mailbox.email or "Неизвестно"

