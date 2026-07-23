from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from .backup_status import BackupJobStatus, BackupStatus, get_backup_status
from .models import MailboxAccount, MarketplaceAlert, ServiceEvent
from .seed_data import DEMO_MAILBOX_EMAIL
from .server_timers import ServerTimerStatus, ServerTimersStatus, get_server_timers_status
from .telegram.config import get_telegram_config

TELEGRAM_ERROR_LOOKBACK = timedelta(hours=24)


@dataclass(frozen=True)
class HealthCheck:
    ok: bool
    status: str
    detail: str = ""


def build_health_report(*, include_deploy_checks: bool = False) -> dict:
    now = timezone.now()
    backup_status = get_backup_status()
    timers_status = get_server_timers_status()
    checks = {
        "database": _check_database(),
        "active_mailbox": _check_active_mailbox(),
        "telegram": _check_telegram_config(),
        "telegram_delivery": _check_recent_telegram_delivery_errors(now),
        "gmail_recent_check": _check_recent_gmail_check(now),
        "open_service_errors": _check_open_service_errors(),
        "backup": _check_backup_status(backup_status),
        "server_timers": _check_server_timers(timers_status),
    }

    if include_deploy_checks:
        checks["secrets"] = _check_deploy_secrets()
        checks["debug"] = HealthCheck(
            ok=not settings.DEBUG,
            status="ok" if not settings.DEBUG else "warning",
            detail="DJANGO_DEBUG should be False on production deploys.",
        )
        checks["demo_data"] = _check_no_demo_mailbox()

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
        "summary": _build_health_summary(now),
        "labels": _build_health_labels(),
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
        return HealthCheck(False, "error", _("No active mailboxes configured."))
    return HealthCheck(
        True,
        "ok",
        _("Active mailboxes: %(count)s.") % {"count": count},
    )


def _check_telegram_config() -> HealthCheck:
    config = get_telegram_config()
    if not config.bot_token:
        return HealthCheck(False, "error", _("TELEGRAM_BOT_TOKEN is not configured."))
    if not config.allowed_chat_ids:
        return HealthCheck(False, "error", _("No allowed Telegram chat is configured."))
    return HealthCheck(
        True,
        "ok",
        _("Allowed chats: %(count)s.") % {"count": len(config.allowed_chat_ids)},
    )


def _check_recent_telegram_delivery_errors(now) -> HealthCheck:
    since = now - TELEGRAM_ERROR_LOOKBACK
    count = MarketplaceAlert.objects.exclude(telegram_error="").filter(
        created_at__gte=since,
    ).count()

    if count:
        return HealthCheck(
            False,
            "warning",
            _("Telegram send errors in the last 24 hours: %(count)s.")
            % {"count": count},
        )

    return HealthCheck(
        True,
        "ok",
        _("No Telegram send errors in the last 24 hours."),
    )


def _check_recent_gmail_check(now) -> HealthCheck:
    newest_check = MailboxAccount.objects.filter(is_active=True).aggregate(
        last_checked_at=Max("last_checked_at"),
    )["last_checked_at"]
    if newest_check is None:
        return HealthCheck(False, "warning", _("No Gmail check has run yet."))

    stale_after = timedelta(minutes=settings.ARGUS_GMAIL_CHECK_STALE_MINUTES)
    age = now - newest_check
    if age > stale_after:
        minutes = int(age.total_seconds() // 60)
        return HealthCheck(
            False,
            "warning",
            _("Last Gmail check was %(minutes)s minutes ago.")
            % {"minutes": minutes},
        )
    return HealthCheck(
        True,
        "ok",
        _("Last Gmail check: %(timestamp)s.")
        % {"timestamp": newest_check.isoformat()},
    )


def _check_open_service_errors() -> HealthCheck:
    count = ServiceEvent.objects.filter(
        status=ServiceEvent.Status.OPEN,
        severity__in=[ServiceEvent.Severity.ERROR, ServiceEvent.Severity.CRITICAL],
    ).count()
    if count:
        return HealthCheck(
            False,
            "error",
            _("Open service errors: %(count)s.") % {"count": count},
        )
    return HealthCheck(True, "ok", _("No open service errors."))


def _check_backup_status(status: BackupStatus) -> HealthCheck:
    if not status.is_available:
        return HealthCheck(
            True,
            "unavailable",
            _("Backup status is unavailable because systemd is not available."),
        )

    details = "; ".join(_backup_job_detail(job) for job in status.jobs)
    if status.is_healthy:
        return HealthCheck(True, "ok", details)
    return HealthCheck(False, "error", details)


def _backup_job_detail(job: BackupJobStatus) -> str:
    label = _("Local archive") if job.job.key == "local" else _("Remote copy")
    result = _("success") if job.result == "success" else job.result
    timer = _("active") if job.active_state == "active" else job.active_state
    last_run = job.last_run_at or _("not run yet")
    return _("%(label)s: %(result)s (timer: %(timer)s, %(last_run)s: %(timestamp)s)") % {
        "label": label,
        "result": result,
        "timer": timer,
        "last_run": _("Last run"),
        "timestamp": last_run,
    }


def _check_server_timers(status: ServerTimersStatus) -> HealthCheck:
    if not status.is_available:
        return HealthCheck(
            True,
            "unavailable",
            _("Server timer status is unavailable because systemd is not available."),
        )

    details = "; ".join(_server_timer_detail(timer) for timer in status.timers)
    if status.is_healthy:
        return HealthCheck(True, "ok", details)
    return HealthCheck(False, "error", details)


def _server_timer_detail(timer: ServerTimerStatus) -> str:
    labels = {
        "gmail": _("Gmail checks"),
        "unread": _("Unread reminders"),
        "cleanup": _("Lead cleanup"),
        "deploy": _("Automatic deploy"),
        "backup_local": _("Local archive"),
        "backup_remote": _("Remote copy"),
        "health": _("Health monitor"),
    }
    icon = "🟢" if timer.is_healthy else "🔴"
    state = _("active") if timer.active_state == "active" else timer.active_state
    next_run = timer.next_run_at or _("not scheduled")
    details = _("%(label)s: %(state)s, next run: %(next_run)s") % {
        "label": labels[timer.timer.key],
        "state": state,
        "next_run": next_run,
    }
    return f"{icon} {details}"


def _check_deploy_secrets() -> HealthCheck:
    missing = []
    for name in ("SECRET_KEY", "DATABASE_URL", "GMAIL_OAUTH_TOKEN_FERNET_KEY"):
        if not getattr(settings, name, ""):
            missing.append(name)
    if missing:
        return HealthCheck(
            False,
            "error",
            _("Missing deploy settings: %(settings)s.")
            % {"settings": ", ".join(missing)},
        )
    return HealthCheck(True, "ok")


def _check_no_demo_mailbox() -> HealthCheck:
    if MailboxAccount.objects.filter(email__iexact=DEMO_MAILBOX_EMAIL).exists():
        return HealthCheck(
            False,
            "error",
            _("Demo mailbox %(email)s must not exist on production deploys.")
            % {"email": DEMO_MAILBOX_EMAIL},
        )
    return HealthCheck(True, "ok", _("No demo mailbox found."))


def _build_health_summary(now=None) -> dict:
    now = now or timezone.now()
    telegram_error_since = now - TELEGRAM_ERROR_LOOKBACK

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
        telegram_errors_recent=Count(
            "id",
            filter=Q(created_at__gte=telegram_error_since) & ~Q(telegram_error=""),
        ),
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


def _build_health_labels() -> dict:
    return {
        "modal_title": _("Argus service status"),
        "loading": _("Loading service diagnostics..."),
        "open_json": _("Open JSON"),
        "close": _("Close"),
        "service_ok": _("Service is running"),
        "service_degraded": _("There are issues"),
        "checked_at": _("Checked"),
        "mailboxes": _("Mailboxes"),
        "mailbox_active_total": _("%(active)s active / %(total)s total"),
        "connection_errors": _("Connection errors"),
        "leads": _("Leads"),
        "new_leads": _("%(count)s new"),
        "today": _("Today"),
        "open_errors": _("Open errors"),
        "error_critical": _("ERROR / CRITICAL"),
        "component": _("Component"),
        "status": _("Status"),
        "details": _("Details"),
        "status_ok": _("OK"),
        "status_warning": _("Needs attention"),
        "status_error": _("Problem"),
        "load_error": _("Could not load service status."),
        "empty": _("—"),
        "checks": {
            "database": _("Database"),
            "active_mailbox": _("Active mailbox accounts"),
            "telegram": _("Telegram"),
            "telegram_delivery": _("Telegram delivery"),
            "gmail_recent_check": _("Latest Gmail check"),
            "open_service_errors": _("Open service errors"),
            "backup": _("Backups"),
            "server_timers": _("Server timers"),
            "secrets": _("Production secrets"),
            "debug": _("Debug mode"),
            "demo_data": _("Demo data"),
        },
    }
