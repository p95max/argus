from django.core.management.base import BaseCommand, CommandError

from alerts.command_locks import CommandAlreadyRunning, command_lock
from alerts.cleanup import DEFAULT_CLEANUP_OLD_LEADS_DAYS, cleanup_old_leads


class Command(BaseCommand):
    help = "Delete old inactive lead branches grouped by mailbox and listing_id."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_CLEANUP_OLD_LEADS_DAYS,
            help="Only delete inactive branches whose newest alert is older than this many days.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of branches to delete in one run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many branches would be deleted without deleting alerts.",
        )

    def handle(self, *args, **options):
        try:
            with command_lock("cleanup_old_leads"):
                return self._handle_locked(*args, **options)
        except CommandAlreadyRunning as exc:
            self.stdout.write(self.style.WARNING(str(exc)))

    def _handle_locked(self, *args, **options):
        days = options["days"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        if days < 1:
            raise CommandError("--days must be at least 1.")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1.")

        result = cleanup_old_leads(older_than_days=days, limit=limit, dry_run=dry_run)
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run complete. Old inactive branches matched: {result.selected_cases}; alerts deleted: 0."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Cleanup complete. Branches deleted: {result.selected_cases}; alerts deleted: {result.deleted_alerts}."
            )
        )
