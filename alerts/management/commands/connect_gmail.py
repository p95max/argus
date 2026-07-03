from django.core.management.base import BaseCommand

from alerts.gmail import connect_gmail, gmail_credentials_paths


class Command(BaseCommand):
    help = "Run local Gmail OAuth flow and save GOOGLE_TOKEN_FILE."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=0, help="Local OAuth callback port. Default: random.")

    def handle(self, *args, **options):
        credentials_file, token_file = gmail_credentials_paths()
        saved_path = connect_gmail(credentials_file=credentials_file, token_file=token_file, port=options["port"])
        self.stdout.write(self.style.SUCCESS(f"Gmail token saved to {saved_path}"))
