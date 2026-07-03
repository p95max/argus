from dataclasses import dataclass

from asgiref.sync import sync_to_async
from telegram.error import BadRequest

from ..models import MarketplaceAlert
from .keyboards import (
    CALLBACK_STATUS_ACTION,
    CALLBACK_STATUS_UPDATES,
    build_alert_keyboard,
    _parse_callback_data,
)
from .messages import (
    build_alert_message,
    build_daily_summary_message,
    build_mailbox_status_message,
    _build_status_answer,
    _truncate,
)
from .permissions import is_allowed_telegram_actor, is_allowed_update


@dataclass(frozen=True)
class AlertCallbackResult:
    alert: MarketplaceAlert
    answer_text: str
    status_changed: bool


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


async def handle_mailbox_status_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(
            "Этот пользователь или чат не имеет доступа к Argus.",
        )
        return

    text = await sync_to_async(build_mailbox_status_message)()

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def handle_daily_summary_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(
            "Этот пользователь или чат не имеет доступа к Argus.",
        )
        return

    text = await sync_to_async(build_daily_summary_message)()

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
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