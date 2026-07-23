import logging

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from alerts.telegram.config import get_telegram_config
from alerts.telegram.deploy_command import handle_deploy_command
from alerts.telegram.doctor_command import handle_doctor_command
from alerts.telegram.command_menu import publish_telegram_command_menu
from alerts.telegram.help_command import handle_help_command
from alerts.telegram.i18n import get_argus_telegram_language
from alerts.telegram.handlers import (
    handle_alert_callback,
    handle_daily_summary_command,
    handle_gmail_polling_callback,
    handle_gmail_polling_command,
    handle_health_command,
    handle_mailbox_status_command,
    handle_unread_command,
)

logger = logging.getLogger(__name__)


async def log_telegram_error(update, context):
    logger.error(
        "Telegram bot error. update=%s",
        update,
        exc_info=context.error,
    )


async def configure_bot_commands(application):
    try:
        language = await sync_to_async(
            get_argus_telegram_language,
            thread_sensitive=True,
        )()
        count = await publish_telegram_command_menu(application.bot, language)
        logger.info("Published %s Telegram bot command descriptions.", count)
    except Exception:
        logger.exception("Could not publish Telegram bot command descriptions.")


class Command(BaseCommand):
    help = "Run Telegram bot polling for Argus inline button actions and status commands."

    def handle(self, *args, **options):
        config = get_telegram_config()

        if not config.bot_token:
            raise CommandError("TELEGRAM_BOT_TOKEN is not configured.")

        if not config.allowed_chat_ids:
            raise CommandError(
                "TELEGRAM_ALLOWED_CHAT_IDS or TELEGRAM_DEFAULT_CHAT_ID is not configured."
            )

        allowed_chats = ", ".join(sorted(config.allowed_chat_ids))
        allowed_users = ", ".join(sorted(config.allowed_user_ids)) or "any"

        message = (
            "Telegram bot polling started. "
            f"Allowed chats: {allowed_chats}. "
            f"Allowed users: {allowed_users}."
        )

        self.stdout.write(self.style.SUCCESS(message))
        logger.info(message)

        application = (
            ApplicationBuilder()
            .token(config.bot_token)
            .post_init(configure_bot_commands)
            .build()
        )
        application.bot_data["argus_started_at"] = timezone.now()

        application.add_error_handler(log_telegram_error)
        application.add_handler(
            CallbackQueryHandler(
                handle_alert_callback,
                pattern=r"^alert:\d+:(status|in_work|unread|ignored)$",
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                handle_gmail_polling_callback,
                pattern=r"^polling:(status|enable|disable|run_now)$",
            )
        )
        application.add_handler(
            CommandHandler(
                "help",
                handle_help_command,
            )
        )
        application.add_handler(
            CommandHandler(
                ["status", "mailboxes"],
                handle_mailbox_status_command,
            )
        )
        application.add_handler(
            CommandHandler(
                "summary",
                handle_daily_summary_command,
            )
        )
        application.add_handler(
            CommandHandler(
                "health",
                handle_health_command,
            )
        )
        application.add_handler(
            CommandHandler(
                "doctor",
                handle_doctor_command,
            )
        )
        application.add_handler(
            CommandHandler(
                "deploy",
                handle_deploy_command,
            )
        )
        application.add_handler(
            CommandHandler(
                "unread",
                handle_unread_command,
            )
        )
        application.add_handler(
            CommandHandler(
                "polling",
                handle_gmail_polling_command,
            )
        )

        try:
            application.run_polling(
                allowed_updates=[
                    "callback_query",
                    "message",
                ],
                drop_pending_updates=True,
            )
        finally:
            logger.info("Telegram bot polling stopped.")
