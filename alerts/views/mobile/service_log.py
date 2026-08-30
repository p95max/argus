from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import dashboard
from ...gmail.gmail import mark_gmail_messages_read
from ...models import MarketplaceAlert, ServiceEvent
from ...services.attention import filter_needs_attention


def _safe_next_url(request):
    fallback = reverse("mobile_dashboard")
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
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "process_all_attention_alerts":
            return _process_all_attention_alerts(request)
        return _clear_service_events(request)
    return dashboard.mobile_dashboard(request)


@login_required
@require_POST
def mobile_clear_service_events(request):
    return _clear_service_events(request)


def _process_all_attention_alerts(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied("Only staff users can process attention alerts.")

    alerts = filter_needs_attention(
        MarketplaceAlert.objects.select_related("mailbox")
    )
    alert_count = alerts.count()
    if not alert_count:
        messages.info(request, "Обращений, требующих внимания, уже нет.")
        return redirect(_safe_next_url(request))

    gmail_messages_by_mailbox = defaultdict(list)
    mailboxes = {}
    for alert in alerts:
        if not alert.gmail_message_id:
            continue
        gmail_messages_by_mailbox[alert.mailbox_id].append(alert.gmail_message_id)
        mailboxes[alert.mailbox_id] = alert.mailbox

    alerts.update(
        alert_status=MarketplaceAlert.AlertStatus.ARCHIVED,
        taken_by=None,
        taken_by_label="",
        taken_at=None,
    )

    gmail_errors = 0
    for mailbox_id, message_ids in gmail_messages_by_mailbox.items():
        try:
            mark_gmail_messages_read(mailboxes[mailbox_id], message_ids)
        except Exception:
            gmail_errors += 1

    messages.success(request, f"Обработано обращений: {alert_count}.")
    if gmail_errors:
        messages.warning(
            request,
            "Часть писем Gmail не удалось пометить прочитанными. "
            "Переподключите ящики, которые ещё используют старые права.",
        )
    return redirect(_safe_next_url(request))


def _clear_service_events(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied("Only a superuser can clear the system log.")

    action = request.POST.get("action", "")
    if action == "clear_resolved_service_events":
        events = ServiceEvent.objects.exclude(status=ServiceEvent.Status.OPEN)
    elif action == "clear_all_service_events":
        events = ServiceEvent.objects.all()
    else:
        raise PermissionDenied("Unknown system log cleanup action.")

    if not events.exists():
        messages.info(request, _("The system log is already empty."))
        return redirect(_safe_next_url(request))

    service_event_count = events.count()
    events.delete()
    messages.success(
        request,
        _("System log cleared. Deleted records: %(count)s.")
        % {"count": service_event_count},
    )
    return redirect(_safe_next_url(request))
