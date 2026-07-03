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
            raise CommandError("TELEGRAM_ALLOWED_CHAT_IDS or TELEGRAM_DEFAULT_CHAT_ID is not configured.")

        application = ApplicationBuilder().token(config.bot_token).build()
        application.add_handler(CallbackQueryHandler(handle_alert_callback, pattern=r"^alert:\d+:(in_work|unread|ignored)$"))
        self.stdout.write(self.style.SUCCESS("Telegram bot polling started."))
        application.run_polling()
