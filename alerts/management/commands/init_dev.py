import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from alerts.seed_data import seed_demo_alerts, seed_lead_flags


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Create or update the local development admin user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=os.environ.get("DEV_ADMIN_USERNAME", "admin"),
            help="Admin username. Defaults to DEV_ADMIN_USERNAME or admin.",
        )
        parser.add_argument(
            "--email",
            default=os.environ.get("DEV_ADMIN_EMAIL", "admin@example.local"),
            help="Admin email. Defaults to DEV_ADMIN_EMAIL.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("init_dev can only run when DEBUG=True.")

        username = options["username"].strip()
        email = options["email"].strip()
        password = os.environ.get("DEV_ADMIN_PASSWORD", "").strip()

        if not username:
            raise CommandError("DEV_ADMIN_USERNAME must not be empty.")
        if not email:
            raise CommandError("DEV_ADMIN_EMAIL must not be empty.")
        if not password:
            raise CommandError("DEV_ADMIN_PASSWORD is required in .env.local.")

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
            },
        )

        changed_fields = []
        for field, value in {
            "email": email,
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        }.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)

        user.set_password(password)
        changed_fields.append("password")
        user.save()
        created_flags, updated_flags = seed_lead_flags()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created dev admin user '{username}'."))
        else:
            changed = ", ".join(changed_fields)
            self.stdout.write(self.style.SUCCESS(f"Updated dev admin user '{username}' ({changed})."))

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded lead flags: created {created_flags}, updated {updated_flags}."
            )
        )

        if env_bool("DEV_SEED_SAMPLE_DATA", default=True):
            created_alerts, updated_alerts = seed_demo_alerts()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded demo alerts: created {created_alerts}, updated {updated_alerts}."
                )
            )
