from django.core.management.base import BaseCommand, CommandError

from alerts.telegram import send_system_telegram_alert


class Command(BaseCommand):
    help = "Send an operational Argus message to Telegram."

    def add_arguments(self, parser):
        parser.add_argument("title")
        parser.add_argument("--details", default="")
        parser.add_argument("--chat-id", help="Telegram chat ID. Defaults to TELEGRAM_DEFAULT_CHAT_ID.")

    def handle(self, *args, **options):
        try:
            send_system_telegram_alert(options["title"], details=options["details"], chat_id=options["chat_id"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Telegram system message sent."))
