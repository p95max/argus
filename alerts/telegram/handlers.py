import html
import logging
import shlex
import subprocess

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from telegram.error import BadRequest

from ..command_locks import CommandAlreadyRunning, command_lock
from ..models import MarketplaceAlert
from .config import get_telegram_config
from .keyboards import (
    CALLBACK_STATUS_ACTION,
    CALLBACK_STATUS_UPDATES,
    build_alert_keyboard,
    _parse_callback_data,
)
from .messages import (
    build_alert_message,
    build_daily_summary_message,
    build_health_message,
    build_mailbox_status_message,
    _build_status_answer,
    _truncate,
)
from .permissions import (
    is_allowed_telegram_actor,
    is_allowed_update,
    is_default_chat_update,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertCallbackResult:
    alert: MarketplaceAlert
    answer_text: str
    status_changed: bool


async def handle_alert_callback(update, context):
    query = update.callback_query

    if query is None:
        logger.warning("Telegram callback handler called without callback_query.")
        return

    chat_id = str(query.message.chat_id) if query.message else ""
    user_id = str(query.from_user.id) if query.from_user else ""

    logger.info(
        "Telegram callback received. chat_id=%s user_id=%s data=%s",
        chat_id,
        user_id,
        query.data,
    )

    try:
        result = await sync_to_async(handle_alert_callback_action)(
            query.data,
            chat_id=chat_id,
            user_id=user_id,
        )
    except PermissionError:
        logger.warning(
            "Telegram callback rejected by permission. chat_id=%s user_id=%s data=%s",
            chat_id,
            user_id,
            query.data,
        )
        await _safe_answer_callback(
            query,
            "Этот пользователь или чат не имеет доступа к Argus.",
            show_alert=True,
        )
        return
    except ValueError as exc:
        logger.warning(
            "Telegram callback rejected. chat_id=%s user_id=%s data=%s error=%s",
            chat_id,
            user_id,
            query.data,
            exc,
        )
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
        logger.info(
            "Telegram callback status checked. chat_id=%s user_id=%s alert_id=%s",
            chat_id,
            user_id,
            result.alert.id,
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

    logger.info(
        "Telegram callback status changed. chat_id=%s user_id=%s alert_id=%s status=%s",
        chat_id,
        user_id,
        result.alert.id,
        result.alert.alert_status,
    )


async def handle_mailbox_status_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info(
        "Telegram status command received. chat_id=%s user_id=%s",
        chat_id,
        user_id,
    )

    if not is_allowed_update(update):
        logger.warning(
            "Telegram status command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
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

    logger.info(
        "Telegram status command handled. chat_id=%s user_id=%s",
        chat_id,
        user_id,
    )


async def handle_daily_summary_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info(
        "Telegram summary command received. chat_id=%s user_id=%s",
        chat_id,
        user_id,
    )

    if not is_allowed_update(update):
        logger.warning(
            "Telegram summary command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
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

    logger.info(
        "Telegram summary command handled. chat_id=%s user_id=%s",
        chat_id,
        user_id,
    )


async def handle_health_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info("Telegram health command received. chat_id=%s user_id=%s", chat_id, user_id)

    if not is_allowed_update(update):
        logger.warning(
            "Telegram health command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            "Этот пользователь или чат не имеет доступа к Argus.",
        )
        return
    bot_started_at = context.application.bot_data.get("argus_started_at")
    text = await sync_to_async(build_health_message)(bot_started_at=bot_started_at)

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram health command handled. chat_id=%s user_id=%s", chat_id, user_id)


async def handle_help_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info("Telegram help command received. chat_id=%s user_id=%s", chat_id, user_id)

    if not _is_default_chat_admin_update(update):
        logger.warning(
            "Telegram help command rejected. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            "Подсказка команд доступна только в TELEGRAM_DEFAULT_CHAT_ID.",
        )
        return

    await update.effective_message.reply_text(
        build_bot_help_message(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram help command handled. chat_id=%s user_id=%s", chat_id, user_id)


async def handle_deploy_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info("Telegram deploy command received. chat_id=%s user_id=%s", chat_id, user_id)

    if not _is_default_chat_admin_update(update):
        logger.warning(
            "Telegram deploy command rejected. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            "🚫 /deploy доступен только в TELEGRAM_DEFAULT_CHAT_ID.",
        )
        return

    await update.effective_message.reply_text(
        "🚀 Запускаю ручной деплой Argus…",
    )

    text = await sync_to_async(build_manual_deploy_message)()

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram deploy command handled. chat_id=%s user_id=%s", chat_id, user_id)


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
    update_fields = ["alert_status", "updated_at"]
    if alert.alert_status == MarketplaceAlert.AlertStatus.IN_WORK:
        alert.taken_by = None
        alert.taken_by_label = f"Telegram user {user_id}" if user_id else f"Telegram chat {chat_id}"
        alert.taken_at = timezone.now()
        update_fields.extend(["taken_by", "taken_by_label", "taken_at"])
    elif alert.alert_status == MarketplaceAlert.AlertStatus.UNREAD:
        alert.taken_by = None
        alert.taken_by_label = ""
        alert.taken_at = None
        update_fields.extend(["taken_by", "taken_by_label", "taken_at"])

    alert.save(update_fields=update_fields)

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


def build_bot_help_message() -> str:
    return "\n".join(
        [
            "🤖 <b>Argus bot: команды</b>",
            "",
            "/health — состояние сервиса",
            "/status или /mailboxes — статус Gmail-ящиков",
            "/summary — дневная сводка",
            "/doctor — диагностика VPS/script",
            "/deploy — ручной деплой из TELEGRAM_DEFAULT_CHAT_ID",
            "/help — эта подсказка",
        ]
    )


def build_manual_deploy_message() -> str:
    config = get_telegram_config()
    command = config.manual_deploy_command.strip()

    if not command:
        return (
            "🚨 <b>Argus deploy</b>\n"
            "<pre>TELEGRAM_MANUAL_DEPLOY_COMMAND is not configured.</pre>"
        )

    try:
        args = shlex.split(command)
    except ValueError as exc:
        return (
            "🚨 <b>Argus deploy</b>\n"
            f"<pre>Invalid TELEGRAM_MANUAL_DEPLOY_COMMAND: {html.escape(str(exc))}</pre>"
        )

    if not args:
        return (
            "🚨 <b>Argus deploy</b>\n"
            "<pre>TELEGRAM_MANUAL_DEPLOY_COMMAND is empty.</pre>"
        )

    try:
        with command_lock(
            "telegram_manual_deploy",
            timeout=config.manual_deploy_timeout_seconds + 30,
        ):
            result = subprocess.run(
                args,
                cwd=settings.BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=config.manual_deploy_timeout_seconds,
                check=False,
            )
    except CommandAlreadyRunning:
        return "🟠 <b>Argus deploy</b>\n<pre>Deploy is already running.</pre>"
    except FileNotFoundError:
        return (
            "🚨 <b>Argus deploy</b>\n"
            f"<pre>{html.escape(args[0])} not found</pre>"
        )
    except subprocess.TimeoutExpired:
        return (
            "🚨 <b>Argus deploy</b>\n"
            f"<pre>Deploy timed out after {config.manual_deploy_timeout_seconds} seconds.</pre>"
        )

    output = result.stdout.strip() or "(no output)"

    if len(output) > 3300:
        output = "... truncated ...\n" + output[-3300:]

    icon = "✅" if result.returncode == 0 else "🚨"

    return (
        f"{icon} <b>Argus deploy finished</b>\n"
        f"<pre>{html.escape(output)}</pre>"
    )


def build_doctor_script_message() -> str:
    try:
        result = subprocess.run(
            ["/bin/bash", "/usr/local/bin/argus-doctor.sh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=25,
            check=False,
        )
    except FileNotFoundError:
        return "🚨 <b>[DEV] Argus doctor</b>\n<pre>/usr/local/bin/argus-doctor.sh not found</pre>"
    except subprocess.TimeoutExpired:
        return "🚨 <b>[DEV] Argus doctor</b>\n<pre>Doctor check timed out after 25 seconds.</pre>"

    output = result.stdout.strip() or "(no output)"

    if len(output) > 3300:
        output = "... truncated ...\n" + output[-3300:]

    icon = "✅" if result.returncode == 0 else "🚨"

    return (
        f"{icon} <b>[DEV] Argus doctor</b>\n"
        f"<pre>{html.escape(output)}</pre>"
    )


def _is_default_chat_admin_update(update) -> bool:
    return is_default_chat_update(update) and is_allowed_update(update)


async def _safe_answer_callback(query, text: str, show_alert: bool = False) -> None:
    try:
        await query.answer(
            _truncate(text, 190),
            show_alert=show_alert,
        )
    except BadRequest as exc:
        message = str(exc).lower()

        if "query is too old" in message or "query id is invalid":
            logger.warning(
                "Telegram callback answer skipped because query is too old or invalid."
            )
            return

        logger.exception("Telegram callback answer failed.")
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
            logger.info(
                "Telegram alert message edit skipped because message is not modified. alert_id=%s",
                alert.id,
            )
            return
        if "query is too old" in message or "query id is invalid" in message:
            logger.warning(
                "Telegram alert message edit skipped because query is too old or invalid. alert_id=%s",
                alert.id,
            )
            return

        logger.exception(
            "Telegram alert message edit failed. alert_id=%s",
            alert.id,
        )
        raise


async def handle_doctor_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info("Telegram doctor command received. chat_id=%s user_id=%s", chat_id, user_id)

    if not is_allowed_update(update):
        logger.warning(
            "Telegram doctor command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            "Этот пользователь или чат не имеет доступа к Argus.",
        )
        return
    text = await sync_to_async(build_doctor_script_message)()

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram doctor command handled. chat_id=%s user_id=%s", chat_id, user_id)
