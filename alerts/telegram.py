import asyncio
import html
import os
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from .models import MarketplaceAlert


CALLBACK_PREFIX = "alert"
CALLBACK_ACTIONS = {
    "in_work": MarketplaceAlert.AlertStatus.IN_WORK,
    "unread": MarketplaceAlert.AlertStatus.UNREAD,
    "ignored": MarketplaceAlert.AlertStatus.IGNORED,
}


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    default_chat_id: str
    allowed_chat_ids: set[str]
    send_on_gmail_check: bool


def get_telegram_config() -> TelegramConfig:
    default_chat_id = os.environ.get("TELEGRAM_DEFAULT_CHAT_ID", "").strip()
    allowed_chat_ids = {
        item.strip()
        for item in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if item.strip()
    }
    if default_chat_id:
        allowed_chat_ids.add(default_chat_id)

    return TelegramConfig(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        default_chat_id=default_chat_id,
        allowed_chat_ids=allowed_chat_ids,
        send_on_gmail_check=_env_bool("TELEGRAM_SEND_ON_GMAIL_CHECK", default=False),
    )


def should_send_telegram_for_alert(alert: MarketplaceAlert) -> bool:
    return alert.event_type != MarketplaceAlert.EventType.NOISE


def build_alert_message(alert: MarketplaceAlert) -> str:
    title = alert.listing_title or alert.subject or alert.get_event_type_display()
    buyer = alert.buyer_name or "Неизвестно"
    message = alert.message_text or alert.normalized_body or alert.raw_body or "Текст не найден"
    flags = ", ".join(alert.flags.values_list("name", flat=True)) or "нет"

    return "\n".join(
        [
            "<b>Новое обращение</b>",
            f"<b>Покупатель:</b> {html.escape(buyer)}",
            f"<b>Объявление:</b> {html.escape(title)}",
            f"<b>Приоритет:</b> {html.escape(alert.get_priority_display())}",
            f"<b>Тип:</b> {html.escape(alert.get_event_type_display())}",
            f"<b>Флаги:</b> {html.escape(flags)}",
            "",
            html.escape(_truncate(message, 1200)),
        ]
    )


def build_system_message(title: str, details: str = "") -> str:
    lines = ["<b>Argus: системное уведомление</b>", html.escape(title)]
    if details:
        lines.extend(["", html.escape(_truncate(details, 1200))])
    return "\n".join(lines)


def build_alert_keyboard(alert: MarketplaceAlert) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("В работу", callback_data=_callback_data(alert.id, "in_work")),
                InlineKeyboardButton("Снять / не в работе", callback_data=_callback_data(alert.id, "unread")),
            ],
            [InlineKeyboardButton("Игнор", callback_data=_callback_data(alert.id, "ignored"))],
        ]
    )


def send_telegram_alert(alert: MarketplaceAlert, chat_id: str | None = None, bot: Bot | None = None):
    return asyncio.run(async_send_telegram_alert(alert, chat_id=chat_id, bot=bot))


async def async_send_telegram_alert(alert: MarketplaceAlert, chat_id: str | None = None, bot: Bot | None = None):
    config = get_telegram_config()
    target_chat_id = str(chat_id or config.default_chat_id).strip()
    if not target_chat_id:
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")
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
        await sync_to_async(alert.save)(update_fields=["telegram_error", "updated_at"])
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


async def send_system_telegram_message(title: str, details: str = "", chat_id: str | None = None, bot: Bot | None = None):
    config = get_telegram_config()
    target_chat_id = str(chat_id or config.default_chat_id).strip()
    if not target_chat_id:
        raise ValueError("TELEGRAM_DEFAULT_CHAT_ID is not configured.")
    if bot is None:
        if not config.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")
        bot = Bot(token=config.bot_token)
    return await bot.send_message(chat_id=target_chat_id, text=build_system_message(title, details), parse_mode="HTML")


def send_system_telegram_alert(title: str, details: str = "", chat_id: str | None = None, bot: Bot | None = None):
    return asyncio.run(send_system_telegram_message(title, details=details, chat_id=chat_id, bot=bot))


async def handle_alert_callback(update, context):
    query = update.callback_query
    chat_id = str(query.message.chat_id)
    try:
        alert = await sync_to_async(update_alert_status_from_callback)(query.data, chat_id=chat_id)
    except PermissionError:
        await query.answer("Этот чат не имеет доступа к Argus.", show_alert=True)
        return
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
        return

    await query.answer(f"Статус: {alert.get_alert_status_display()}")
    await query.edit_message_reply_markup(reply_markup=build_alert_keyboard(alert))


def update_alert_status_from_callback(callback_data: str, chat_id: str) -> MarketplaceAlert:
    if not is_allowed_chat(chat_id):
        raise PermissionError("Chat is not allowed.")

    alert_id, action = _parse_callback_data(callback_data)
    status = CALLBACK_ACTIONS[action]
    alert = MarketplaceAlert.objects.get(id=alert_id)
    alert.alert_status = status
    alert.save(update_fields=["alert_status", "updated_at"])
    return alert


def is_allowed_chat(chat_id: str) -> bool:
    allowed_chat_ids = get_telegram_config().allowed_chat_ids
    return bool(allowed_chat_ids) and str(chat_id) in allowed_chat_ids


def _callback_data(alert_id: int, action: str) -> str:
    return f"{CALLBACK_PREFIX}:{alert_id}:{action}"


def _parse_callback_data(callback_data: str) -> tuple[int, str]:
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        raise ValueError("Unknown Telegram action.")
    if parts[2] not in CALLBACK_ACTIONS:
        raise ValueError("Unknown Telegram action.")
    try:
        return int(parts[1]), parts[2]
    except ValueError as exc:
        raise ValueError("Unknown Telegram alert.") from exc


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}..."


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
