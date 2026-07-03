from django.core.management.base import BaseCommand, CommandError
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from alerts.telegram.config import get_telegram_config
from alerts.telegram.handlers import (
    handle_alert_callback,
    handle_daily_summary_command,
    handle_mailbox_status_command,
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

        self.stdout.write(
            self.style.SUCCESS(
                "Telegram bot polling started. "
                f"Allowed chats: {', '.join(sorted(config.allowed_chat_ids))}. "
                f"Allowed users: {', '.join(sorted(config.allowed_user_ids)) or 'any'}."
            )
        )

        application = ApplicationBuilder().token(config.bot_token).build()

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

        application.run_polling(
            allowed_updates=[
                "callback_query",
                "message",
            ],
            drop_pending_updates=True,
        )