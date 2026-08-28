import logging
import html
import subprocess

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from django.utils.translation import gettext as _
from telegram.error import BadRequest

from ..gmail.gmail import check_mailbox
from ..models import MailboxAccount, MarketplaceAlert
from ..gmail_polling import (
    GmailPollingCommandError,
    apply_gmail_polling_action,
    get_gmail_polling_status,
)
from .git_status import build_git_deploy_status_text as build_git_deploy_status_text_v2
from .help_command import ACTIVE_BOT_COMMANDS
from .i18n import telegram_gettext, use_argus_telegram_language
from .keyboards import (
    CALLBACK_STATUS_ACTION,
    CALLBACK_STATUS_UPDATES,
    build_alert_keyboard,
    build_gmail_polling_keyboard,
    build_unread_report_keyboard,
    _parse_callback_data,
    parse_gmail_polling_callback_data,
)
from .messages import (
    build_alert_message,
    build_daily_summary_message,
    build_gmail_polling_message,
    build_health_message,
    build_mailbox_status_message,
    build_unread_reminder_report_message,
    _build_status_answer,
    _truncate,
)
from .permissions import is_allowed_telegram_actor, is_allowed_update

logger = logging.getLogger(__name__)
PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."


@dataclass(frozen=True)
class AlertCallbackResult:
    alert: MarketplaceAlert
    answer_text: str
    status_changed: bool


@dataclass(frozen=True)
class GmailPollingCallbackResult:
    answer_text: str
    message_text: str
    is_enabled: bool
    can_control: bool


def _run_with_fresh_db_connection(func, *args, **kwargs):
    close_old_connections()
    try:
        return func(*args, **kwargs)
    finally:
        close_old_connections()


async def _run_db_sync(func, *args, **kwargs):
    return await sync_to_async(_run_with_fresh_db_connection, thread_sensitive=True)(func, *args, **kwargs)


async def handle_alert_callback(update, context):
    query = update.callback_query
    if query is None:
        return
    chat_id = str(query.message.chat_id) if query.message else ""
    user_id = str(query.from_user.id) if query.from_user else ""
    try:
        result = await _run_db_sync(handle_alert_callback_action, query.data, chat_id=chat_id, user_id=user_id)
    except PermissionError:
        await _safe_answer_callback(query, telegram_gettext(PERMISSION_DENIED_MESSAGE), show_alert=True)
        return
    except ValueError as exc:
        await _safe_answer_callback(query, str(exc), show_alert=True)
        return
    if not result.status_changed:
        await _safe_answer_callback(query, result.answer_text, show_alert=True)
        return
    await _safe_answer_callback(query, result.answer_text)
    await _safe_edit_alert_message(query, result.alert)


async def handle_gmail_polling_callback(update, context):
    query = update.callback_query
    if query is None:
        return
    chat_id = str(query.message.chat_id) if query.message else ""
    user_id = str(query.from_user.id) if query.from_user else ""
    try:
        result = await _run_db_sync(handle_gmail_polling_callback_action, query.data, chat_id=chat_id, user_id=user_id)
    except PermissionError:
        await _safe_answer_callback(query, telegram_gettext(PERMISSION_DENIED_MESSAGE), show_alert=True)
        return
    except ValueError as exc:
        await _safe_answer_callback(query, str(exc), show_alert=True)
        return
    await _safe_answer_callback(query, result.answer_text)
    await _safe_edit_gmail_polling_message(query, result)


async def handle_mailbox_status_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(telegram_gettext(PERMISSION_DENIED_MESSAGE))
        return
    text = await _run_db_sync(build_mailbox_status_message)
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def handle_gmail_polling_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(telegram_gettext(PERMISSION_DENIED_MESSAGE))
        return
    status = await sync_to_async(get_gmail_polling_status, thread_sensitive=True)()
    text = await sync_to_async(build_gmail_polling_message, thread_sensitive=True)(status)
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=build_gmail_polling_keyboard(status.is_enabled, getattr(status, "is_available", True)),
        disable_web_page_preview=True,
    )


def _check_gmail_for_new_cases():
    """Synchronously check all active mailboxes and return newly created buyer cases."""
    started_at = timezone.now()
    mailboxes = list(MailboxAccount.objects.filter(is_active=True).order_by("id"))
    if not mailboxes:
        return [], [], "No active mailboxes found."

    errors = []
    for mailbox in mailboxes:
        try:
            check_mailbox(mailbox, max_results=25)
        except Exception as exc:
            logger.exception("Manual Telegram Gmail check failed for %s", mailbox.email)
            errors.append(f"{mailbox.email}: {exc}")

    alerts = list(
        MarketplaceAlert.objects.select_related("mailbox")
        .filter(created_at__gte=started_at, event_type=MarketplaceAlert.EventType.BUYER_MESSAGE)
        .order_by("created_at", "id")
    )
    return alerts, errors, ""


async def handle_check_mail_command(update, context):
    """Run an immediate Gmail check and report only cases created by this run."""
    if not is_allowed_update(update):
        await update.effective_message.reply_text(telegram_gettext(PERMISSION_DENIED_MESSAGE))
        return

    status_message = await update.effective_message.reply_text("🔄 Проверяю новые письма…")
    alerts, errors, fatal = await _run_db_sync(_check_gmail_for_new_cases)

    if fatal:
        await status_message.edit_text(f"⚠️ {html.escape(fatal)}", parse_mode="HTML")
        return

    if not alerts:
        text = "✅ Проверка завершена. Новых кейсов нет."
        if errors:
            text += "\n\n⚠️ Ошибки: " + html.escape("; ".join(errors))
        await status_message.edit_text(text, parse_mode="HTML")
        return

    text = f"🚨 <b>Новые кейсы: {len(alerts)}</b>"
    if errors:
        text += "\n⚠️ Часть ящиков завершилась с ошибкой."
    await status_message.edit_text(text, parse_mode="HTML")

    for alert in alerts:
        alert_text = await _run_db_sync(build_alert_message, alert)
        await update.effective_message.reply_text(
            alert_text,
            parse_mode="HTML",
            reply_markup=build_alert_keyboard(alert),
            disable_web_page_preview=True,
        )


async def handle_daily_summary_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(telegram_gettext(PERMISSION_DENIED_MESSAGE))
        return
    text = await _run_db_sync(build_daily_summary_message)
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def handle_health_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(telegram_gettext(PERMISSION_DENIED_MESSAGE))
        return
    bot_started_at = context.application.bot_data.get("argus_started_at")
    text = await _run_db_sync(build_health_message, bot_started_at=bot_started_at)
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def handle_unread_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(telegram_gettext(PERMISSION_DENIED_MESSAGE))
        return
    text, reply_markup = await _run_db_sync(build_unread_command_report)
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)


@use_argus_telegram_language
def build_unread_command_message(limit: int = 25) -> str:
    return build_unread_command_report(limit)[0]


@use_argus_telegram_language
def build_unread_command_report(limit: int = 25):
    alerts = list(
        MarketplaceAlert.objects.select_related("mailbox")
        .filter(alert_status=MarketplaceAlert.AlertStatus.UNREAD)
        .exclude(event_type=MarketplaceAlert.EventType.NOISE)
        .order_by("created_at", "id")[:limit]
    )
    return build_unread_reminder_report_message(alerts), build_unread_report_keyboard(alerts)


@use_argus_telegram_language
def handle_alert_callback_action(callback_data: str, chat_id: str, user_id: str = "") -> AlertCallbackResult:
    if not is_allowed_telegram_actor(chat_id=chat_id, user_id=user_id):
        raise PermissionError(_("Telegram actor is not allowed."))
    alert_id, action = _parse_callback_data(callback_data)
    try:
        alert = MarketplaceAlert.objects.get(id=alert_id)
    except MarketplaceAlert.DoesNotExist as exc:
        raise ValueError(_("Telegram alert was not found.")) from exc
    if action == CALLBACK_STATUS_ACTION:
        return AlertCallbackResult(alert=alert, answer_text=_build_status_answer(alert), status_changed=False)
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
    return AlertCallbackResult(alert=alert, answer_text=_build_status_answer(alert), status_changed=True)


def update_alert_status_from_callback(callback_data: str, chat_id: str, user_id: str = "") -> MarketplaceAlert:
    return handle_alert_callback_action(callback_data, chat_id, user_id).alert


@use_argus_telegram_language
def handle_gmail_polling_callback_action(callback_data: str, chat_id: str, user_id: str = "") -> GmailPollingCallbackResult:
    if not is_allowed_telegram_actor(chat_id=chat_id, user_id=user_id):
        raise PermissionError(_("Telegram actor is not allowed."))
    action = parse_gmail_polling_callback_data(callback_data)
    if action == "status":
        answer_text = _("Gmail polling status refreshed.")
    else:
        try:
            answer_text = apply_gmail_polling_action(action)
        except GmailPollingCommandError as exc:
            answer_text = _("Gmail polling action failed: %(error)s") % {"error": str(exc)}
    status = get_gmail_polling_status()
    return GmailPollingCallbackResult(
        answer_text=answer_text,
        message_text=build_gmail_polling_message(status),
        is_enabled=status.is_enabled,
        can_control=status.is_available,
    )


def build_doctor_script_message() -> str:
    try:
        result = subprocess.run(["/bin/bash", "/usr/local/bin/argus-doctor.sh"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=25, check=False)
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
    return f"{icon} <b>[DEV] Argus doctor</b>\n<pre>{html.escape(combined_output)}</pre>"


def build_git_deploy_status_text() -> str:
    branch = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    head_sha = _run_git_command(["rev-parse", "--short", "HEAD"])
    head_subject = _run_git_command(["log", "-1", "--pretty=%s"])
    head_date = _run_git_command(["log", "-1", "--date=format:%d.%m.%Y %H:%M:%S", "--pretty=%cd"])
    origin_sha = _run_git_command(["rev-parse", "--short", "origin/master"])
    relation = _build_git_relation_text()
    lines = ["🧬 Git deploy status"]
    if branch: lines.append(f"Branch: {branch}")
    if head_sha: lines.append(f"Local HEAD: {head_sha}")
    if head_subject: lines.append(f"Commit: {head_subject}")
    if head_date: lines.append(f"Date: {head_date}")
    if origin_sha: lines.append(f"Origin/master: {origin_sha}")
    if relation: lines.append(f"Status: {relation}")
    return "\n".join(lines) if len(lines) > 1 else "🧬 Git deploy status\nStatus: git info unavailable"


def _build_git_relation_text() -> str:
    relation = _run_git_command(["rev-list", "--left-right", "--count", "HEAD...origin/master"])
    if not relation: return "unknown"
    parts = relation.split()
    if len(parts) != 2: return "unknown"
    try: ahead, behind = int(parts[0]), int(parts[1])
    except ValueError: return "unknown"
    if ahead == 0 and behind == 0: return "up to date"
    if ahead == 0: return f"behind origin/master by {behind} commit(s)"
    if behind == 0: return f"ahead of origin/master by {ahead} commit(s)"
    return f"diverged: ahead {ahead}, behind {behind}"


def _run_git_command(args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=settings.BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


async def _safe_answer_callback(query, text: str, show_alert: bool = False) -> None:
    try:
        await query.answer(_truncate(text, 190), show_alert=show_alert)
    except BadRequest as exc:
        message = str(exc).lower()
        if "query is too old" in message or "query id is invalid" in message:
            return
        raise


async def _safe_edit_alert_message(query, alert: MarketplaceAlert) -> None:
    try:
        text = await _run_db_sync(build_alert_message, alert)
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=build_alert_keyboard(alert), disable_web_page_preview=True)
    except BadRequest as exc:
        message = str(exc).lower()
        if "message is not modified" in message or "query is too old" in message or "query id is invalid" in message:
            return
        raise


async def _safe_edit_gmail_polling_message(query, result: GmailPollingCallbackResult) -> None:
    try:
        await query.edit_message_text(
            text=result.message_text,
            parse_mode="HTML",
            reply_markup=build_gmail_polling_keyboard(result.is_enabled, result.can_control),
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise
