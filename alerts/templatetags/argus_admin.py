from django import template
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from alerts.models import MailboxAccount, MarketplaceAlert

register = template.Library()


@register.simple_tag
def argus_dashboard_counters():
    today = timezone.localdate()
    alerts = MarketplaceAlert.objects.all()

    status_counts = alerts.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(created_at__date=today)),
        unread=Count("id", filter=Q(alert_status=MarketplaceAlert.AlertStatus.UNREAD)),
        in_work=Count("id", filter=Q(alert_status=MarketplaceAlert.AlertStatus.IN_WORK)),
        ignored=Count("id", filter=Q(alert_status=MarketplaceAlert.AlertStatus.IGNORED)),
        high_priority=Count(
            "id",
            filter=Q(priority__in=[MarketplaceAlert.Priority.HIGH, MarketplaceAlert.Priority.URGENT]),
        ),
        parser_errors=Count(
            "id",
            filter=Q(parse_status__in=[MarketplaceAlert.ParseStatus.ERROR, MarketplaceAlert.ParseStatus.PARTIAL]),
        ),
    )
    mailbox_counts = MailboxAccount.objects.aggregate(
        active=Count("id", filter=Q(is_active=True)),
        errors=Count("id", filter=Q(connection_status=MailboxAccount.ConnectionStatus.ERROR)),
    )

    alerts_url = reverse("admin:alerts_marketplacealert_changelist")
    mailbox_url = reverse("admin:alerts_mailboxaccount_changelist")

    return [
        {
            "label": _("New today"),
            "value": status_counts["today"],
            "icon": "fas fa-calendar-day",
            "class": "info",
            "url": alerts_url,
        },
        {
            "label": _("New"),
            "value": status_counts["unread"],
            "icon": "fas fa-bell",
            "class": "danger",
            "url": f"{alerts_url}?alert_status__exact={MarketplaceAlert.AlertStatus.UNREAD}",
        },
        {
            "label": _("In work"),
            "value": status_counts["in_work"],
            "icon": "fas fa-user-clock",
            "class": "warning",
            "url": f"{alerts_url}?alert_status__exact={MarketplaceAlert.AlertStatus.IN_WORK}",
        },
        {
            "label": _("High priority"),
            "value": status_counts["high_priority"],
            "icon": "fas fa-exclamation-circle",
            "class": "danger",
            "url": alerts_url,
        },
        {
            "label": _("Parser errors"),
            "value": status_counts["parser_errors"],
            "icon": "fas fa-code",
            "class": "warning",
            "url": alerts_url,
        },
        {
            "label": _("Active mailboxes"),
            "value": mailbox_counts["active"],
            "icon": "fas fa-envelope",
            "class": "success",
            "url": mailbox_url,
        },
        {
            "label": _("Mailbox errors"),
            "value": mailbox_counts["errors"],
            "icon": "fas fa-heartbeat",
            "class": "danger",
            "url": f"{mailbox_url}?connection_status__exact={MailboxAccount.ConnectionStatus.ERROR}",
        },
        {
            "label": _("Ignored"),
            "value": status_counts["ignored"],
            "icon": "fas fa-eye-slash",
            "class": "secondary",
            "url": f"{alerts_url}?alert_status__exact={MarketplaceAlert.AlertStatus.IGNORED}",
        },
    ]
