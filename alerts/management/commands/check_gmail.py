import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from alerts.gmail import check_mailbox
from alerts.models import MailboxAccount

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Check active Gmail mailboxes and create alerts for new Kleinanzeigen emails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mailbox",
            help="Mailbox email or ID. Defaults to all active mailboxes.",
        )
        parser.add_argument(
            "--max-results",
            type=int,
            default=settings.GMAIL_CHECK_MAX_RESULTS,
            help="Maximum Gmail messages to fetch per mailbox.",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            default=settings.GMAIL_CHECK_FAIL_ON_ERROR,
            help="Exit with non-zero status if at least one mailbox check fails.",
        )

    def handle(self, *args, **options):
        queryset = MailboxAccount.objects.filter(is_active=True)

        if options["mailbox"]:
            value = options["mailbox"].strip()
            if value.isdigit():
                queryset = queryset.filter(id=int(value))
            else:
                queryset = queryset.filter(email=value)

        mailboxes = list(queryset)
        if not mailboxes:
            raise CommandError("No active mailboxes found.")

        max_results = options["max_results"]
        fail_on_error = options["fail_on_error"]

        total_created = 0
        total_duplicates = 0
        total_failed = 0

        for mailbox in mailboxes:
            try:
                result = check_mailbox(mailbox, max_results=max_results)
            except Exception as exc:
                total_failed += 1
                logger.exception("Gmail check failed for mailbox %s", mailbox.email)
                self.stderr.write(self.style.ERROR(f"{mailbox.email}: {exc}"))
                continue

            total_created += result.created
            total_duplicates += result.duplicates

            logger.info(
                "Gmail check completed for %s: fetched=%s created=%s duplicates=%s",
                mailbox.email,
                result.fetched,
                result.created,
                result.duplicates,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"{mailbox.email}: fetched {result.fetched}, "
                    f"created {result.created}, duplicates {result.duplicates}"
                )
            )

        summary = (
            f"Done. Created {total_created}, duplicates {total_duplicates}, "
            f"failed {total_failed}."
        )

        if total_failed:
            self.stderr.write(self.style.WARNING(summary))
            if fail_on_error:
                raise CommandError(f"Gmail check failed for {total_failed} mailbox(es).")
        else:
            self.stdout.write(self.style.SUCCESS(summary))