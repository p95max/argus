import json

from django.core.management.base import BaseCommand, CommandError

from alerts.health import build_health_report


NON_BLOCKING_WARNING_CHECKS = {
    "gmail_recent_check",
    "telegram_delivery",
}


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
        blocking_checks = _get_blocking_checks(report)
        report["deploy_ready"] = not blocking_checks

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            deploy_status = "ok" if report["deploy_ready"] else "degraded"
            self.stdout.write(f"Argus deploy status: {deploy_status}")
            for name, check in report["checks"].items():
                marker = _check_marker(name, check)
                detail = f" - {check['detail']}" if check["detail"] else ""
                self.stdout.write(f"{marker} {name}: {check['status']}{detail}")

        if blocking_checks:
            raise CommandError("Argus deploy readiness checks failed.")


def _get_blocking_checks(report: dict) -> dict:
    return {
        name: check
        for name, check in report["checks"].items()
        if not check["ok"]
        and not (
            name in NON_BLOCKING_WARNING_CHECKS
            and check["status"] == "warning"
        )
    }


def _check_marker(name: str, check: dict) -> str:
    if check["ok"]:
        return "OK"
    if name in NON_BLOCKING_WARNING_CHECKS and check["status"] == "warning":
        return "WARN"
    return "FAIL"
