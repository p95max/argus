import json

from django.core.management.base import BaseCommand, CommandError

from alerts.health import build_health_report


class Command(BaseCommand):
    help = "Run production readiness checks for Argus deploys."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the full deploy check report as JSON.",
        )

    def handle(self, *args, **options):
        report = build_health_report(include_deploy_checks=True)

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"Argus deploy status: {report['status']}")
            for name, check in report["checks"].items():
                marker = "OK" if check["ok"] else "FAIL"
                detail = f" - {check['detail']}" if check["detail"] else ""
                self.stdout.write(f"{marker} {name}: {check['status']}{detail}")

        if not report["ok"]:
            raise CommandError("Argus deploy readiness checks failed.")
