from django.core.management.base import BaseCommand, CommandError

from alerts.gmail import build_gmail_service, check_mailbox
from alerts.models import MailboxAccount


class Command(BaseCommand):
    help = "Check active Gmail mailboxes and create alerts for new Kleinanzeigen emails."

    def add_arguments(self, parser):
        parser.add_argument("--mailbox", help="Mailbox email or ID. Defaults to all active mailboxes.")
        parser.add_argument("--max-results", type=int, default=25)

    def handle(self, *args, **options):
        queryset = MailboxAccount.objects.filter(is_active=True)
        if options["mailbox"]:
            value = options["mailbox"]
            if value.isdigit():
                queryset = queryset.filter(id=int(value))
            else:
                queryset = queryset.filter(email=value)

        mailboxes = list(queryset)
        if not mailboxes:
            raise CommandError("No active mailboxes found.")

        try:
            service = build_gmail_service()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        total_created = 0
        total_duplicates = 0
        for mailbox in mailboxes:
            try:
                result = check_mailbox(mailbox, service=service, max_results=options["max_results"])
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"{mailbox.email}: {exc}"))
                continue

            total_created += result.created
            total_duplicates += result.duplicates
            self.stdout.write(
                self.style.SUCCESS(
                    f"{mailbox.email}: fetched {result.fetched}, created {result.created}, duplicates {result.duplicates}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done. Created {total_created}, duplicates {total_duplicates}.")
        )
