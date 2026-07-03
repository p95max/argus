from django.core.management.base import BaseCommand, CommandError

from alerts.models import MarketplaceAlert
from alerts.telegram import send_telegram_alert


class Command(BaseCommand):
    help = "Send a marketplace alert to Telegram."

    def add_arguments(self, parser):
        parser.add_argument("alert_id", type=int)
        parser.add_argument("--chat-id", help="Telegram chat ID. Defaults to TELEGRAM_DEFAULT_CHAT_ID.")

    def handle(self, *args, **options):
        try:
            alert = MarketplaceAlert.objects.get(id=options["alert_id"])
        except MarketplaceAlert.DoesNotExist as exc:
            raise CommandError(f"Alert {options['alert_id']} was not found.") from exc

        try:
            send_telegram_alert(alert, chat_id=options["chat_id"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Telegram alert sent for alert {alert.id}."))
