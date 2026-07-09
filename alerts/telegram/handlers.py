import logging
import html
import subprocess

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from telegram.error import BadRequest

from ..models import MarketplaceAlert
from .git_status import build_git_deploy_status_text as build_git_deploy_status_text_v2
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
    build_unread_reminder_report_message,
    _build_status_answer,
    _truncate,
)
from .permissions import is_allowed_telegram_actor, is_allowed_update


logger = logging.getLogger(__name__)


ACTIVE_BOT_COMMANDS = (
    ("help", "что умеет бот и список команд"),
    ("status", "статус Gmail-ящиков и последние проверки"),
    ("mailboxes", "то же, что /status"),
    ("summary", "сводка по обращениям за сегодня"),
    ("unread", "общий отчёт по непрочитанным обращениям"),
    ("health", "здоровье сервиса: DB, Gmail, Telegram, ошибки"),
    ("doctor", "production doctor: systemd, git, health и deploy status"),
)


@dataclass(frozen=True)
class AlertCallbackResult:
    alert: MarketplaceAlert
    answer_text: str
    status_changed: bool


def _run_with_fresh_db_connection(func, *args, **kwargs):
    close_old_connections()
    try:
        return func(*args, **kwargs)
    finally:
        close_old_connections()


async def _run_db_sync(func, *args, **kwargs):
    return await sync_to_async(_run_with_fresh_db_connection, thread_sensitive=True)(
        func,
        *args,
        **kwargs,
    )


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
        result = await _run_db_sync(
            handle_alert_callback_action,
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

    text = await _run_db_sync(build_mailbox_status_message)

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


async def handle_help_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info("Telegram help command received. chat_id=%s user_id=%s", chat_id, user_id)

    if not is_allowed_update(update):
        logger.warning(
            "Telegram help command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            "Этот пользователь или чат не имеет доступа к Argus.",
        )
        return

    await update.effective_message.reply_text(
        build_help_message(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram help command handled. chat_id=%s user_id=%s", chat_id, user_id)


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

    text = await _run_db_sync(build_daily_summary_message)

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
    text = await _run_db_sync(build_health_message, bot_started_at=bot_started_at)

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram health command handled. chat_id=%s user_id=%s", chat_id, user_id)


async def handle_unread_command(update, context):
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    user_id = str(update.effective_user.id) if update.effective_user else ""

    logger.info("Telegram unread command received. chat_id=%s user_id=%s", chat_id, user_id)

    if not is_allowed_update(update):
        logger.warning(
            "Telegram unread command rejected by permission. chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await update.effective_message.reply_text(
            "Этот пользователь или чат не имеет доступа к Argus.",
        )
        return

    text = await _run_db_sync(build_unread_command_message)

    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram unread command handled. chat_id=%s user_id=%s", chat_id, user_id)


def build_unread_command_message(limit: int = 25) -> str:
    alerts = list(
        MarketplaceAlert.objects.select_related("mailbox")
        .filter(alert_status=MarketplaceAlert.AlertStatus.UNREAD)
        .exclude(event_type=MarketplaceAlert.EventType.NOISE)
        .order_by("created_at", "id")[:limit]
    )
    return build_unread_reminder_report_message(alerts)


def build_help_message() -> str:
    lines = [
        "🤖 <b>Argus: что умеет бот</b>",
        "",
        "Бот присылает новые обращения из Gmail, даёт быстрые кнопки статуса и ведёт в мобильную админку.",
        "Ещё он показывает здоровье сервиса, непрочитанные обращения и краткую операционную сводку.",
        "",
        "⚡ <b>Активные команды</b>",
    ]
    lines.extend(
        f"/{command} — {html.escape(description)}"
        for command, description in ACTIVE_BOT_COMMANDS
    )
    lines.extend(
        [
            "",
            "🔘 <b>Кнопки в alert-ах</b>",
            "В работу · Новое · Игнор · Статус · Open Mobile",
        ]
    )
    return "\n".join(lines)


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
    git_output = build_git_deploy_status_text_v2()
    combined_output = f"{output}\n\n{git_output}" if git_output else output

    if len(combined_output) > 3300:
        combined_output = "... truncated ...\n" + combined_output[-3300:]

    icon = "✅" if result.returncode == 0 else "🚨"

    return (
        f"{icon} <b>[DEV] Argus doctor</b>\n"
        f"<pre>{html.escape(combined_output)}</pre>"
    )


def build_git_deploy_status_text() -> str:
    branch = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    head_sha = _run_git_command(["rev-parse", "--short", "HEAD"])
    head_subject = _run_git_command(["log", "-1", "--pretty=%s"])
    head_date = _run_git_command(["log", "-1", "--date=format:%d.%m.%Y %H:%M:%S", "--pretty=%cd"])
    origin_sha = _run_git_command(["rev-parse", "--short", "origin/master"])
    relation = _build_git_relation_text()

    lines = ["🧬 Git deploy status"]
    if branch:
        lines.append(f"Branch: {branch}")
    if head_sha:
        lines.append(f"Local HEAD: {head_sha}")
    if head_subject:
        lines.append(f"Commit: {head_subject}")
    if head_date:
        lines.append(f"Date: {head_date}")
    if origin_sha:
        lines.append(f"Origin/master: {origin_sha}")
    if relation:
        lines.append(f"Status: {relation}")

    if len(lines) == 1:
        return "🧬 Git deploy status\nStatus: git info unavailable"

    return "\n".join(lines)


def _build_git_relation_text() -> str:
    relation = _run_git_command(["rev-list", "--left-right", "--count", "HEAD...origin/master"])
    if not relation:
        return "unknown"

    parts = relation.split()
    if len(parts) != 2:
        return "unknown"

    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        return "unknown"

    if ahead == 0 and behind == 0:
        return "up to date"
    if ahead == 0:
        return f"behind origin/master by {behind} commit(s)"
    if behind == 0:
        return f"ahead of origin/master by {ahead} commit(s)"
    return f"diverged: ahead {ahead}, behind {behind}"


def _run_git_command(args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=settings.BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


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
        text = await _run_db_sync(build_alert_message, alert)

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
