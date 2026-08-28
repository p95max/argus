import html

from django.utils import timezone

from ..monitoring.health import build_health_report
from .i18n import use_argus_telegram_language
from .permissions import is_allowed_update

PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."


async def handle_health_command(update, context):
    if not is_allowed_update(update):
        await update.effective_message.reply_text(PERMISSION_DENIED_MESSAGE)
        return

    from .handlers import _run_db_sync

    bot_started_at = context.application.bot_data.get("argus_started_at")
    text = await _run_db_sync(build_technical_health_message, bot_started_at=bot_started_at)
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@use_argus_telegram_language
def build_technical_health_message(bot_started_at=None) -> str:
    report = build_health_report()
    summary = report["summary"]
    checks = report["checks"]
    telegram_errors_recent = summary["alerts"].get("telegram_errors_recent", 0)
    open_errors = summary["open_service_errors"]
    backup_details = checks["backup"]["detail"].split("; ")
    timer_details = checks["server_timers"]["detail"].split("; ")

    uptime = "unknown"
    if bot_started_at:
        delta = timezone.now() - bot_started_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        uptime = f"{hours}h {minutes}m"

    def label(name):
        return "OK" if checks[name]["ok"] else checks[name]["status"].upper()

    def icon(name):
        if checks[name]["ok"]:
            return "🟢"
        return "🔴" if checks[name]["status"] == "error" else "🟠"

    lines = [
        "🩺 <b>Argus: health</b>",
        "",
        f"{icon('database')} <b>DB:</b> {html.escape(label('database'))}",
        f"{icon('active_mailbox')} <b>Mailboxes:</b> {html.escape(label('active_mailbox'))}",
        f"{icon('gmail_recent_check')} <b>Gmail:</b> {html.escape(label('gmail_recent_check'))}",
        f"{icon('telegram')} <b>Telegram:</b> {html.escape(label('telegram'))}",
        f"{icon('telegram_delivery')} <b>Telegram delivery:</b> {telegram_errors_recent} errors / 24h",
        "",
        "💾 <b>Backups:</b>",
        *[f"   {html.escape(detail)}" for detail in backup_details],
        "⏱ <b>Server timers:</b>",
        *[f"   {html.escape(detail)}" for detail in timer_details],
        "",
        f"🔴 <b>Open service errors:</b> {open_errors}",
        f"🤖 <b>Bot uptime:</b> {html.escape(uptime)}",
    ]
    return "\n".join(lines)
