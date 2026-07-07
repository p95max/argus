from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import MailboxAccount, MarketplaceAlert, ServiceEvent
from .telegram.config import get_telegram_config


@dataclass(frozen=True)
class HealthCheck:
    ok: bool
    status: str
    detail: str = ""


def build_health_report(*, include_deploy_checks: bool = False) -> dict:
    now = timezone.now()
    checks = {
        "database": _check_database(),
        "active_mailbox": _check_active_mailbox(),
        "telegram": _check_telegram_config(),
        "gmail_recent_check": _check_recent_gmail_check(now),
        "open_service_errors": _check_open_service_errors(),
    }

    if include_deploy_checks:
        checks["secrets"] = _check_deploy_secrets()
        checks["debug"] = HealthCheck(
            ok=not settings.DEBUG,
            status="ok" if not settings.DEBUG else "warning",
            detail="DJANGO_DEBUG should be False on production deploys.",
        )

    overall_ok = all(check.ok for check in checks.values())
    return {
        "status": "ok" if overall_ok else "degraded",
        "ok": overall_ok,
        "generated_at": now.isoformat(),
        "checks": {
            key: {
                "ok": check.ok,
                "status": check.status,
                "detail": check.detail,
            }
            for key, check in checks.items()
        },
        "summary": _build_health_summary(),
    }


def _check_database() -> HealthCheck:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return HealthCheck(False, "error", str(exc))
    return HealthCheck(True, "ok")


def _check_active_mailbox() -> HealthCheck:
    count = MailboxAccount.objects.filter(is_active=True).count()
    if count < 1:
        return HealthCheck(False, "error", "No active mailboxes configured.")
    return HealthCheck(True, "ok", f"Active mailboxes: {count}.")


def _check_telegram_config() -> HealthCheck:
    config = get_telegram_config()
    if not config.bot_token:
        return HealthCheck(False, "error", "TELEGRAM_BOT_TOKEN is not configured.")
    if not config.allowed_chat_ids:
        return HealthCheck(False, "error", "No allowed Telegram chat is configured.")
    return HealthCheck(True, "ok", f"Allowed chats: {len(config.allowed_chat_ids)}.")


def _check_recent_gmail_check(now) -> HealthCheck:
    newest_check = MailboxAccount.objects.filter(is_active=True).aggregate(
        last_checked_at=Max("last_checked_at"),
    )["last_checked_at"]
    if newest_check is None:
        return HealthCheck(False, "warning", "No Gmail check has run yet.")

    stale_after = timedelta(minutes=settings.ARGUS_GMAIL_CHECK_STALE_MINUTES)
    age = now - newest_check
    if age > stale_after:
        minutes = int(age.total_seconds() // 60)
        return HealthCheck(
            False,
            "warning",
            f"Last Gmail check was {minutes} minutes ago.",
        )
    return HealthCheck(True, "ok", f"Last Gmail check: {newest_check.isoformat()}.")


def _check_open_service_errors() -> HealthCheck:
    count = ServiceEvent.objects.filter(
        status=ServiceEvent.Status.OPEN,
        severity__in=[ServiceEvent.Severity.ERROR, ServiceEvent.Severity.CRITICAL],
    ).count()
    if count:
        return HealthCheck(False, "error", f"Open service errors: {count}.")
    return HealthCheck(True, "ok", "No open service errors.")


def _check_deploy_secrets() -> HealthCheck:
    missing = []
    for name in ("SECRET_KEY", "DATABASE_URL", "GMAIL_OAUTH_TOKEN_FERNET_KEY"):
        if not getattr(settings, name, ""):
            missing.append(name)
    if missing:
        return HealthCheck(False, "error", f"Missing deploy settings: {', '.join(missing)}.")
    return HealthCheck(True, "ok")


def _build_health_summary() -> dict:
    mailbox_counts = MailboxAccount.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        errors=Count(
            "id",
            filter=Q(connection_status=MailboxAccount.ConnectionStatus.ERROR),
        ),
        last_checked_at=Max("last_checked_at"),
        last_success_at=Max("last_success_at"),
    )
    alert_counts = MarketplaceAlert.objects.aggregate(
        unread=Count(
            "id",
            filter=Q(alert_status=MarketplaceAlert.AlertStatus.UNREAD),
        ),
        today=Count("id", filter=Q(created_at__date=timezone.localdate())),
    )
    open_errors = ServiceEvent.objects.filter(
        status=ServiceEvent.Status.OPEN,
        severity__in=[ServiceEvent.Severity.ERROR, ServiceEvent.Severity.CRITICAL],
    ).count()
    return {
        "mailboxes": mailbox_counts,
        "alerts": alert_counts,
        "open_service_errors": open_errors,
    }
