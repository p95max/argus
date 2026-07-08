import logging

from django.core.management.base import BaseCommand, CommandError

from alerts.command_locks import CommandAlreadyRunning, command_lock
from alerts.gmail.gmail import check_mailbox
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
            default=25,
        )

    def handle(self, *args, **options):
        try:
            with command_lock("check_gmail"):
                return self._handle_locked(*args, **options)
        except CommandAlreadyRunning as exc:
            self.stdout.write(self.style.WARNING(str(exc)))

    def _handle_locked(self, *args, **options):
        queryset = MailboxAccount.objects.filter(is_active=True)

        if options["mailbox"]:
            value = options["mailbox"]

            if value.isdigit():
                queryset = queryset.filter(id=int(value))
            else:
                queryset = queryset.filter(email=value)

        raw_mailboxes = list(queryset)

        if not raw_mailboxes:
            raise CommandError("No active mailboxes found.")

        mailboxes = []
        total_skipped = 0

        for mailbox in raw_mailboxes:
            email = (mailbox.email or "").strip()

            if not email:
                total_skipped += 1

                logger.warning(
                    "Skipping active Gmail mailbox without email. mailbox_id=%s",
                    mailbox.pk,
                )

                MailboxAccount.objects.filter(pk=mailbox.pk).update(is_active=False)

                self.stderr.write(
                    self.style.WARNING(
                        f"Mailbox #{mailbox.pk}: skipped and disabled because email is empty."
                    )
                )
                continue

            mailboxes.append(mailbox)

        if not mailboxes:
            raise CommandError("No connected active mailboxes found.")

        total_created = 0
        total_duplicates = 0
        total_failed = 0

        for mailbox in mailboxes:
            try:
                result = check_mailbox(
                    mailbox,
                    max_results=options["max_results"],
                )
            except FileNotFoundError as exc:
                total_skipped += 1

                logger.warning(
                    "Skipping Gmail mailbox because credentials/token file is missing. "
                    "mailbox_id=%s email=%s error=%s",
                    mailbox.pk,
                    mailbox.email,
                    exc,
                )

                MailboxAccount.objects.filter(pk=mailbox.pk).update(is_active=False)

                self.stderr.write(
                    self.style.WARNING(
                        f"{mailbox.email}: skipped and disabled because Gmail credentials/token "
                        f"file is missing: {exc}"
                    )
                )
                continue
            except Exception as exc:
                total_failed += 1

                logger.exception("Gmail check failed for mailbox %s", mailbox.email)

                self.stderr.write(
                    self.style.ERROR(f"{mailbox.email}: {exc}")
                )
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {total_created}, "
                f"duplicates {total_duplicates}, "
                f"failed {total_failed}, skipped {total_skipped}."
            )
        )