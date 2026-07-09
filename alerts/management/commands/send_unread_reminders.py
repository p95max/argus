import logging

from django.core.management.base import BaseCommand, CommandError

from alerts.reminders import (
    DEFAULT_MIN_AGE_MINUTES,
    DEFAULT_REMINDER_INTERVAL_MINUTES,
    unread_alerts_due_for_reminder,
)
from alerts.telegram.messages import should_send_telegram_for_alert
from alerts.telegram.sender import send_telegram_reminder_report


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send Telegram reminders for unread alerts that have not been handled."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-age-minutes",
            type=int,
            default=DEFAULT_MIN_AGE_MINUTES,
            help="Only remind about unread alerts at least this old.",
        )
        parser.add_argument(
            "--reminder-interval-minutes",
            type=int,
            default=DEFAULT_REMINDER_INTERVAL_MINUTES,
            help="Do not remind about the same alert more often than this.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Maximum reminders to send in one run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print due alerts without sending Telegram messages.",
        )

    def handle(self, *args, **options):
        min_age_minutes = options["min_age_minutes"]
        reminder_interval_minutes = options["reminder_interval_minutes"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        if min_age_minutes < 1:
            raise CommandError("--min-age-minutes must be at least 1.")
        if reminder_interval_minutes < 1:
            raise CommandError("--reminder-interval-minutes must be at least 1.")
        if limit < 1:
            raise CommandError("--limit must be at least 1.")

        alerts = list(
            unread_alerts_due_for_reminder(
                min_age_minutes=min_age_minutes,
                reminder_interval_minutes=reminder_interval_minutes,
            )[:limit]
        )

        sent = 0
        failed = 0
        skipped_quiet = 0
        eligible_alerts = []

        for alert in alerts:
            label = f"alert #{alert.id} ({alert.mailbox.email})"
            if not should_send_telegram_for_alert(alert):
                skipped_quiet += 1
                self.stdout.write(f"Quiet hours skipped: {label}")
                continue

            eligible_alerts.append(alert)

        if dry_run:
            for alert in eligible_alerts:
                self.stdout.write(f"Due reminder: alert #{alert.id} ({alert.mailbox.email})")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Due reminders {len(eligible_alerts)}, "
                    f"quiet-hours skipped {skipped_quiet}."
                )
            )
            return

        if eligible_alerts:
            try:
                send_telegram_reminder_report(eligible_alerts)
            except Exception as exc:
                failed = len(eligible_alerts)
                logger.exception(
                    "Unread reminder report failed for %s alerts",
                    len(eligible_alerts),
                )
                self.stderr.write(self.style.ERROR(f"Unread reminder report: {exc}"))
            else:
                sent = len(eligible_alerts)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Reminder report sent: {len(eligible_alerts)} alerts."
                    )
                )

        else:
            self.stdout.write("No unread reminders to send.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Sent {sent}, failed {failed}, quiet-hours skipped {skipped_quiet}, "
                "skipped by limit or filters handled by queryset."
            )
        )
