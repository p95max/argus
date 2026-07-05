import logging

from django.core.management.base import BaseCommand, CommandError

from alerts.models import MarketplaceAlert
from alerts.telegram.sender import send_telegram_alert


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send a marketplace alert to Telegram."

    def add_arguments(self, parser):
        parser.add_argument("alert_id", type=int)
        parser.add_argument(
            "--chat-id",
            help="Telegram chat ID. Defaults to TELEGRAM_DEFAULT_CHAT_ID.",
        )

    def handle(self, *args, **options):
        alert_id = options["alert_id"]
        chat_id = options["chat_id"]

        logger.info(
            "Telegram alert command started. alert_id=%s chat_id=%s",
            alert_id,
            chat_id or "default",
        )

        try:
            alert = MarketplaceAlert.objects.get(id=alert_id)
        except MarketplaceAlert.DoesNotExist as exc:
            logger.warning(
                "Telegram alert command failed: alert not found. alert_id=%s",
                alert_id,
            )
            raise CommandError(f"Alert {alert_id} was not found.") from exc

        logger.info(
            "Telegram alert command loaded alert. alert_id=%s status=%s event_type=%s priority=%s",
            alert.id,
            alert.alert_status,
            alert.event_type,
            alert.priority,
        )

        try:
            message = send_telegram_alert(alert, chat_id=chat_id)
        except Exception as exc:
            logger.exception(
                "Telegram alert command failed during send. alert_id=%s chat_id=%s",
                alert.id,
                chat_id or "default",
            )
            raise CommandError(str(exc)) from exc

        if message is None:
            self.stdout.write(self.style.WARNING(f"Telegram alert skipped for alert {alert.id}."))
            return

        telegram_message_id = getattr(message, "message_id", "") or alert.telegram_message_id

        logger.info(
            "Telegram alert command finished. alert_id=%s telegram_chat_id=%s telegram_message_id=%s",
            alert.id,
            alert.telegram_chat_id,
            telegram_message_id,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Telegram alert sent for alert {alert.id}. "
                f"chat_id={alert.telegram_chat_id}, "
                f"message_id={telegram_message_id}"
            )
        )
