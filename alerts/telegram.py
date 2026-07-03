import asyncio
import html
import os
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from .models import MarketplaceAlert


CALLBACK_PREFIX = "alert"
CALLBACK_STATUS_ACTION = "status"

CALLBACK_STATUS_UPDATES = {
    "in_work": MarketplaceAlert.AlertStatus.IN_WORK,
    "unread": MarketplaceAlert.AlertStatus.UNREAD,
    "ignored": MarketplaceAlert.AlertStatus.IGNORED,
}


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    default_chat_id: str
    allowed_chat_ids: set[str]
    allowed_user_ids: set[str]
    send_on_gmail_check: bool


@dataclass(frozen=True)
class AlertCallbackResult:
    alert: MarketplaceAlert
    answer_text: str
    status_changed: bool


def get_telegram_config() -> TelegramConfig:
    default_chat_id = os.environ.get("TELEGRAM_DEFAULT_CHAT_ID", "").strip()

    allowed_chat_ids = {
        item.strip()
        for item in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if item.strip()
    }
    if default_chat_id:
        allowed_chat_ids.add(default_chat_id)

    allowed_user_ids = {
        item.strip()
        for item in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if item.strip()
    }

    return TelegramConfig(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        default_chat_id=default_chat_id,
        allowed_chat_ids=allowed_chat_ids,
        allowed_user_ids=allowed_user_ids,
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
            f"<b>ID:</b> {alert.id}",
            f"<b>Статус:</b> {html.escape(alert.get_alert_status_display())}",
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
    lines = [
        "<b>Argus: системное уведомление</b>",
        html.escape(title),
    ]

    if details:
        lines.extend(
            [
                "",
                html.escape(_truncate(details, 1200)),
            ]
        )

    return "\n".join(lines)


def build_alert_keyboard(alert: MarketplaceAlert) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Статус",
                    callback_data=_callback_data(alert.id, CALLBACK_STATUS_ACTION),
                ),
            ],
            [
                InlineKeyboardButton(
                    "В работу",
                    callback_data=_callback_data(alert.id, "in_work"),
                ),
                InlineKeyboardButton(
                    "Снять / не в работе",
                    callback_data=_callback_data(alert.id, "unread"),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Игнор",
                    callback_data=_callback_data(alert.id, "ignored"),
                ),
            ],
        ]
    )


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


async def handle_alert_callback(update, context):
    query = update.callback_query

    if query is None:
        return

    chat_id = str(query.message.chat_id) if query.message else ""
    user_id = str(query.from_user.id) if query.from_user else ""

    try:
        result = await sync_to_async(handle_alert_callback_action)(
            query.data,
            chat_id=chat_id,
            user_id=user_id,
        )
    except PermissionError:
        await _safe_answer_callback(
            query,
            "Этот пользователь или чат не имеет доступа к Argus.",
            show_alert=True,
        )
        return
    except ValueError as exc:
        await _safe_answer_callback(
            query,
            str(exc),
            show_alert=True,
        )
        return

    if not result.status_changed:
        await _safe_answer_callback(
            query,
            result.answer_text,
            show_alert=True,
        )
        return

    await _safe_answer_callback(
        query,
        result.answer_text,
    )

    await _safe_edit_alert_message(
        query,
        result.alert,
    )

def handle_alert_callback_action(
    callback_data: str,
    chat_id: str,
    user_id: str = "",
) -> AlertCallbackResult:
    if not is_allowed_telegram_actor(chat_id=chat_id, user_id=user_id):
        raise PermissionError("Telegram actor is not allowed.")

    alert_id, action = _parse_callback_data(callback_data)

    try:
        alert = MarketplaceAlert.objects.get(id=alert_id)
    except MarketplaceAlert.DoesNotExist as exc:
        raise ValueError("Telegram alert was not found.") from exc

    if action == CALLBACK_STATUS_ACTION:
        return AlertCallbackResult(
            alert=alert,
            answer_text=_build_status_answer(alert),
            status_changed=False,
        )

    alert.alert_status = CALLBACK_STATUS_UPDATES[action]
    alert.save(
        update_fields=[
            "alert_status",
            "updated_at",
        ]
    )

    return AlertCallbackResult(
        alert=alert,
        answer_text=_build_status_answer(alert),
        status_changed=True,
    )


def update_alert_status_from_callback(
    callback_data: str,
    chat_id: str,
    user_id: str = "",
) -> MarketplaceAlert:
    result = handle_alert_callback_action(
        callback_data=callback_data,
        chat_id=chat_id,
        user_id=user_id,
    )
    return result.alert


def is_allowed_chat(chat_id: str) -> bool:
    config = get_telegram_config()

    if not config.allowed_chat_ids:
        return False

    return str(chat_id) in config.allowed_chat_ids


def is_allowed_telegram_actor(chat_id: str, user_id: str = "") -> bool:
    config = get_telegram_config()

    if not config.allowed_chat_ids:
        return False

    if str(chat_id) not in config.allowed_chat_ids:
        return False

    if not config.allowed_user_ids:
        return True

    return bool(user_id) and str(user_id) in config.allowed_user_ids


def _callback_data(alert_id: int, action: str) -> str:
    return f"{CALLBACK_PREFIX}:{alert_id}:{action}"


def _parse_callback_data(callback_data: str) -> tuple[int, str]:
    if not callback_data:
        raise ValueError("Unknown Telegram action.")

    parts = callback_data.split(":")

    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        raise ValueError("Unknown Telegram action.")

    action = parts[2]
    if action != CALLBACK_STATUS_ACTION and action not in CALLBACK_STATUS_UPDATES:
        raise ValueError("Unknown Telegram action.")

    try:
        alert_id = int(parts[1])
    except ValueError as exc:
        raise ValueError("Unknown Telegram alert.") from exc

    return alert_id, action


def _build_status_answer(alert: MarketplaceAlert) -> str:
    title = alert.listing_title or alert.subject or alert.get_event_type_display()

    return (
        f"#{alert.id}: "
        f"{alert.get_alert_status_display()} · "
        f"{alert.get_priority_display()} · "
        f"{_truncate(title, 70)}"
    )


async def _safe_answer_callback(query, text: str, show_alert: bool = False) -> None:
    try:
        await query.answer(
            _truncate(text, 190),
            show_alert=show_alert,
        )
    except BadRequest as exc:
        message = str(exc).lower()

        if "query is too old" in message or "query id is invalid" in message:
            return

        raise


async def _safe_edit_alert_message(query, alert: MarketplaceAlert) -> None:
    try:
        text = await sync_to_async(build_alert_message)(alert)

        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=build_alert_keyboard(alert),
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        message = str(exc).lower()

        if "message is not modified" in message:
            return

        if "query is too old" in message or "query id is invalid" in message:
            return

        raise


def _truncate(value: str, limit: int) -> str:
    value = value.strip()

    if len(value) <= limit:
        return value

    return f"{value[: limit - 1]}..."


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }