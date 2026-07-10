import html
import logging

from django.utils.translation import gettext as _

from .i18n import telegram_gettext, use_argus_telegram_language
from .permissions import is_allowed_update


logger = logging.getLogger(__name__)

ACTIVE_BOT_COMMANDS = (
    ("help", "what the bot can do and the command list"),
    ("status", "Gmail mailbox status and latest checks"),
    ("mailboxes", "same as /status"),
    ("summary", "today's lead summary"),
    ("unread", "single report for unread leads"),
    ("health", "service health: DB, Gmail, Telegram, errors"),
    ("doctor", "production doctor: systemd, git, health and deploy status"),
    (
        "deploy",
        "queue an immediate production deploy and report queue, start, and result",
    ),
)

PERMISSION_DENIED_MESSAGE = "This user or chat does not have access to Argus."


@use_argus_telegram_language
def build_help_message() -> str:
    lines = [
        _("🤖 <b>Argus: what the bot can do</b>"),
        "",
        _(
            "The bot sends new Gmail leads, provides quick status buttons, "
            "and links to the mobile admin."
        ),
        _(
            "It also shows service health, unread leads, and a short operational summary."
        ),
        "",
        _("⚡ <b>Active commands</b>"),
    ]
    lines.extend(
        f"/{command} — {html.escape(_(description))}"
        for command, description in ACTIVE_BOT_COMMANDS
    )
    lines.extend(
        [
            "",
            _("🔘 <b>Alert buttons</b>"),
            _("Take to work · New · Ignore · Status · Open Mobile"),
        ]
    )
    return "\n".join(lines)


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
            telegram_gettext(PERMISSION_DENIED_MESSAGE),
        )
        return

    await update.effective_message.reply_text(
        build_help_message(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    logger.info("Telegram help command handled. chat_id=%s user_id=%s", chat_id, user_id)
