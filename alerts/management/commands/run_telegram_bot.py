from django.core.management.base import BaseCommand, CommandError
from telegram.ext import ApplicationBuilder, CallbackQueryHandler

from alerts.telegram import get_telegram_config, handle_alert_callback


class Command(BaseCommand):
    help = "Run Telegram bot polling for Argus inline button actions."

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

        application.run_polling(
            allowed_updates=["callback_query"],
            drop_pending_updates=True,
        )