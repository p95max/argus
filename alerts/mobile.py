from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .attention import filter_needs_attention, needs_attention_alert_q
from .command_locks import CommandAlreadyRunning, command_lock
from .gmail.gmail import check_mailbox
from .gmail_polling import get_gmail_polling_status
from .health import build_health_report
from .models import MailboxAccount, MarketplaceAlert, ServiceEvent, TelegramSettings
from .permissions import can_manage_mailboxes, can_view_mailbox_operations


MOBILE_ALERTS_PER_PAGE = 5


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


def _require_superuser(user):
    if not user.is_active or not user.is_superuser:
        raise PermissionDenied("Only a superuser can clear the system log.")


def _require_mailbox_manage_permission(user):
    if not can_manage_mailboxes(user):
        raise PermissionDenied("You do not have permission to manage mailboxes.")


def _safe_next_url(request, fallback_name="mobile_dashboard"):
    fallback = reverse(fallback_name)
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


@login_required
def mobile_dashboard(request):
    _require_staff(request.user)

    if request.method == "POST":
        _require_superuser(request.user)
        action = request.POST.get("action", "")

        if action == "clear_resolved_service_events":
            events = ServiceEvent.objects.exclude(status=ServiceEvent.Status.OPEN)
        elif action == "clear_all_service_events":
            events = ServiceEvent.objects.all()
        else:
            raise PermissionDenied("Unknown system log cleanup action.")

        deleted_count, _ = events.delete()
        messages.success(
            request,
            _("System log cleared. Deleted records: %(count)s.")
            % {"count": deleted_count},
        )
        return redirect(_safe_next_url(request))

    today = timezone.localdate()
    alerts = (
        MarketplaceAlert.objects.select_related("mailbox", "taken_by")
        .prefetch_related("flags")
        .order_by("-received_at", "-created_at")
    )

    view_mode = request.GET.get("view", "attention")
    base_alerts = alerts

    if view_mode == "today":
        alerts = alerts.filter(created_at__date=today)
    elif view_mode == "mine":
        alerts = alerts.filter(
            alert_status=MarketplaceAlert.AlertStatus.IN_WORK,
            taken_by=request.user,
        )
    elif view_mode == "ignored":
        alerts = alerts.filter(alert_status=MarketplaceAlert.AlertStatus.IGNORED)
    elif view_mode == "archived":
        alerts = alerts.filter(alert_status=MarketplaceAlert.AlertStatus.ARCHIVED)
    elif view_mode == "noise":
        alerts = alerts.filter(event_type=MarketplaceAlert.EventType.NOISE)
    elif view_mode == "attention":
        alerts = filter_needs_attention(alerts)
    elif view_mode == "system":
        alerts = MarketplaceAlert.objects.none()

    alerts_page = None
    if view_mode != "system":
        alerts_page = Paginator(alerts, MOBILE_ALERTS_PER_PAGE).get_page(
            request.GET.get("page")
        )
        alerts = alerts_page.object_list

    service_events = ServiceEvent.objects.none()
    if view_mode == "system":
        service_events = ServiceEvent.objects.select_related(
            "mailbox",
            "alert",
        ).order_by("-last_seen_at", "-created_at")

    settings = TelegramSettings.load()

    alert_counts = base_alerts.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(created_at__date=today)),
        attention=Count("id", filter=needs_attention_alert_q()),
        unread=Count("id", filter=Q(alert_status=MarketplaceAlert.AlertStatus.UNREAD)),
        mine=Count(
            "id",
            filter=Q(
                alert_status=MarketplaceAlert.AlertStatus.IN_WORK,
                taken_by=request.user,
            ),
        ),
        ignored=Count("id", filter=Q(alert_status=MarketplaceAlert.AlertStatus.IGNORED)),
        archived=Count("id", filter=Q(alert_status=MarketplaceAlert.AlertStatus.ARCHIVED)),
        noise=Count("id", filter=Q(event_type=MarketplaceAlert.EventType.NOISE)),
        urgent=Count(
            "id",
            filter=Q(
                priority__in=[
                    MarketplaceAlert.Priority.HIGH,
                    MarketplaceAlert.Priority.URGENT,
                ]
            ),
        ),
    )
    service_open_errors = ServiceEvent.objects.filter(
        status=ServiceEvent.Status.OPEN,
        severity__in=[
            ServiceEvent.Severity.ERROR,
            ServiceEvent.Severity.CRITICAL,
        ],
    ).count()

    mailboxes = MailboxAccount.objects.order_by("email")
    if not can_view_mailbox_operations(request.user):
        mailboxes = MailboxAccount.objects.none()

    mailbox_status = mailboxes.aggregate(
        total=Count("id"),
        errors=Count(
            "id",
            filter=Q(connection_status=MailboxAccount.ConnectionStatus.ERROR),
        ),
        last_checked_at=Max("last_checked_at"),
        last_success_at=Max("last_success_at"),
    )
    gmail_summary = {
        "status": "OK"
        if mailbox_status["total"] and not mailbox_status["errors"]
        else "ERROR"
        if mailbox_status["errors"]
        else "NOT READY",
        "last_checked_at": mailbox_status["last_checked_at"],
        "last_success_at": mailbox_status["last_success_at"],
        "today_alerts": alert_counts["today"],
    }
    gmail_polling = get_gmail_polling_status()
    health_report = build_health_report()

    context = {
        "alerts": alerts,
        "alerts_page": alerts_page,
        "service_events": service_events[:30],
        "mailboxes": mailboxes,
        "mailbox_status": mailbox_status,
        "gmail_summary": gmail_summary,
        "gmail_polling": gmail_polling,
        "health_report": health_report,
        "view_mode": view_mode,
        "alert_counts": alert_counts,
        "service_open_errors": service_open_errors,
        "telegram_settings": settings,
        "can_manage_mailboxes": can_manage_mailboxes(request.user),
        "admin_alert_changelist_url": reverse(
            "admin:alerts_marketplacealert_changelist"
        ),
        "admin_mailbox_changelist_url": reverse(
            "admin:alerts_mailboxaccount_changelist"
        ),
        "admin_telegram_settings_url": reverse(
            "admin:alerts_telegramsettings_change",
            args=[settings.id],
        ),
    }
    return render(request, "mobile/dashboard.html", context)


@login_required
def mobile_alert_detail(request, alert_id):
    _require_staff(request.user)

    alert = get_object_or_404(
        MarketplaceAlert.objects.select_related("mailbox", "taken_by").prefetch_related(
            "flags"
        ),
        id=alert_id,
    )

    context = {
        "alert": alert,
        "can_manage_mailboxes": can_manage_mailboxes(request.user),
        "admin_alert_url": reverse("admin:alerts_marketplacealert_change", args=[alert.id]),
        "admin_mailbox_url": reverse(
            "admin:alerts_mailboxaccount_change",
            args=[alert.mailbox_id],
        ),
    }
    return render(request, "mobile/alert_detail.html", context)


@login_required
@require_POST
def mobile_update_alert_status(request, alert_id):
    _require_staff(request.user)

    alert = get_object_or_404(MarketplaceAlert, id=alert_id)
    status = request.POST.get("status")

    if status not in MarketplaceAlert.AlertStatus.values:
        raise PermissionDenied("Unknown alert status.")

    alert.alert_status = status
    update_fields = ["alert_status", "updated_at"]

    if status == MarketplaceAlert.AlertStatus.IN_WORK:
        alert.taken_by = request.user
        alert.taken_by_label = request.user.get_full_name() or request.user.get_username()
        alert.taken_at = timezone.now()
        update_fields.extend(["taken_by", "taken_by_label", "taken_at"])

    elif status in [
        MarketplaceAlert.AlertStatus.UNREAD,
        MarketplaceAlert.AlertStatus.IGNORED,
        MarketplaceAlert.AlertStatus.ARCHIVED,
    ]:
        alert.taken_by = None
        alert.taken_by_label = ""
        alert.taken_at = None
        update_fields.extend(["taken_by", "taken_by_label", "taken_at"])

    alert.save(update_fields=update_fields)

    return redirect(_safe_next_url(request))


@login_required
@require_POST
def mobile_toggle_quiet_hours(request):
    _require_staff(request.user)

    settings = TelegramSettings.load()
    settings.quiet_hours_enabled = not settings.quiet_hours_enabled
    settings.save(update_fields=["quiet_hours_enabled", "updated_at"])

    return redirect(_safe_next_url(request))


@login_required
@require_POST
def mobile_service_event_action(request, event_id):
    _require_staff(request.user)

    event = get_object_or_404(ServiceEvent, id=event_id)
    action = request.POST.get("action", "")

    if action == "mark_recovered":
        event.status = ServiceEvent.Status.RECOVERED
        event.resolved_at = timezone.now()
        event.save(update_fields=["status", "resolved_at", "updated_at"])
        messages.success(request, "Service event marked recovered.")
    elif action == "ignore":
        event.status = ServiceEvent.Status.IGNORED
        event.resolved_at = timezone.now()
        event.save(update_fields=["status", "resolved_at", "updated_at"])
        messages.success(request, "Service event ignored.")
    else:
        raise PermissionDenied("Unknown service event action.")

    return redirect(_safe_next_url(request))


@login_required
@require_POST
def mobile_check_mailbox_now(request, mailbox_id):
    _require_mailbox_manage_permission(request.user)

    mailbox = get_object_or_404(MailboxAccount, id=mailbox_id)
    result = check_mailbox(mailbox)
    messages.success(
        request,
        _(
            "Mail checked: fetched=%(fetched)s, created=%(created)s, duplicates=%(duplicates)s."
        )
        % {
            "fetched": result.fetched,
            "created": result.created,
            "duplicates": result.duplicates,
        },
    )
    return redirect(_safe_next_url(request))


@login_required
@require_POST
def mobile_check_gmail_now(request):
    _require_mailbox_manage_permission(request.user)

    try:
        with command_lock("check_gmail"):
            summary = _run_mobile_gmail_check()
    except CommandAlreadyRunning:
        messages.warning(
            request,
            _("🔄 Mailbox check is already running. Try again a little later."),
        )
        return redirect(_safe_next_url(request))

    messages.success(
        request,
        _(
            "Mail checked: mailboxes=%(mailboxes)s, fetched=%(fetched)s, "
            "created=%(created)s, duplicates=%(duplicates)s."
        )
        % summary,
    )
    return redirect(_safe_next_url(request))


def _run_mobile_gmail_check():
    summary = {"mailboxes": 0, "fetched": 0, "created": 0, "duplicates": 0}
    mailboxes = MailboxAccount.objects.filter(is_active=True).order_by("email")
    for mailbox in mailboxes:
        result = check_mailbox(mailbox)
        summary["mailboxes"] += 1
        summary["fetched"] += result.fetched
        summary["created"] += result.created
        summary["duplicates"] += result.duplicates
    return summary
