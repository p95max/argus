import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from telegram import BotCommand, BotCommandScopeChat
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from alerts.telegram.config import get_telegram_config
from alerts.telegram.handlers import (
    handle_alert_callback,
    handle_daily_summary_command,
    handle_deploy_command,
    handle_doctor_command,
    handle_health_command,
    handle_help_command,
    handle_mailbox_status_command,
)

logger = logging.getLogger(__name__)


async def log_telegram_error(update, context):
    logger.error(
        "Telegram bot error. update=%s",
        update,
        exc_info=context.error,
    )


async def configure_default_chat_commands(application):
    config = get_telegram_config()
    if not config.default_chat_id:
        logger.info("Telegram default chat commands skipped: TELEGRAM_DEFAULT_CHAT_ID is not configured.")
        return

    await application.bot.set_my_commands(
        [
            BotCommand("health", "Состояние сервиса"),
            BotCommand("status", "Статус Gmail-ящиков"),
            BotCommand("summary", "Дневная сводка"),
            BotCommand("doctor", "Диагностика VPS"),
            BotCommand("deploy", "Ручной деплой"),
            BotCommand("help", "Подсказка команд"),
        ],
        scope=BotCommandScopeChat(chat_id=config.default_chat_id),
    )
    logger.info(
        "Telegram default chat commands configured. chat_id=%s",
        config.default_chat_id,
    )


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
            .post_init(configure_default_chat_commands)
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
                ["help", "start"],
                handle_help_command,
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
