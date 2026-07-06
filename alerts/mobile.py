from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .attention import filter_needs_attention
from .models import MailboxAccount, MarketplaceAlert
from .permissions import can_manage_mailboxes, can_view_mailbox_operations


def _require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Mobile control panel is available only for staff users.")


@login_required
def mobile_dashboard(request):
    _require_staff(request.user)

    alerts = (
        MarketplaceAlert.objects.select_related("mailbox", "taken_by")
        .prefetch_related("flags")
        .order_by("-received_at", "-created_at")
    )
    view_mode = request.GET.get("view", "attention")
    if view_mode == "attention":
        alerts = filter_needs_attention(alerts)

    mailboxes = MailboxAccount.objects.order_by("email")
    if not can_view_mailbox_operations(request.user):
        mailboxes = MailboxAccount.objects.none()

    context = {
        "alerts": alerts[:30],
        "mailboxes": mailboxes,
        "view_mode": view_mode,
        "can_manage_mailboxes": can_manage_mailboxes(request.user),
        "admin_alert_changelist_url": reverse("admin:alerts_marketplacealert_changelist"),
        "admin_mailbox_changelist_url": reverse("admin:alerts_mailboxaccount_changelist"),
    }
    return render(request, "mobile/dashboard.html", context)


@login_required
def mobile_alert_detail(request, alert_id):
    _require_staff(request.user)

    alert = get_object_or_404(
        MarketplaceAlert.objects.select_related("mailbox", "taken_by").prefetch_related("flags"),
        id=alert_id,
    )
    context = {
        "alert": alert,
        "can_manage_mailboxes": can_manage_mailboxes(request.user),
        "admin_alert_url": reverse("admin:alerts_marketplacealert_change", args=[alert.id]),
        "admin_mailbox_url": reverse("admin:alerts_mailboxaccount_change", args=[alert.mailbox_id]),
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
    elif status == MarketplaceAlert.AlertStatus.UNREAD:
        alert.taken_by = None
        alert.taken_by_label = ""
        alert.taken_at = None
        update_fields.extend(["taken_by", "taken_by_label", "taken_at"])

    alert.save(update_fields=update_fields)
    return redirect(request.POST.get("next") or reverse("mobile_dashboard"))
