from django.contrib import admin, messages
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..cleanup import close_cases_for_alerts
from ..models import LeadFlag, MailboxAccount, MarketplaceAlert, NoiseAlert
from .ui import NeedsAttentionFilter, status_badge


@admin.register(MarketplaceAlert)
class MarketplaceAlertAdmin(admin.ModelAdmin):
    list_display = (
        "display_title",
        "buyer_name",
        "mailbox",
        "event_type_badge",
        "status_badge",
        "taken_by_display",
        "priority_badge",
        "risk_badge",
        "needs_attention_badge",
        "parse_status_badge",
        "last_reminded_at",
        "received_at",
    )
    list_filter = (
        NeedsAttentionFilter,
        "mailbox",
        "alert_status",
        "priority",
        "event_type",
        "parse_status",
        "flags",
    )
    search_fields = (
        "listing_title",
        "buyer_name",
        "subject",
        "message_text",
        "listing_id",
    )
    filter_horizontal = ("flags",)
    readonly_fields = (
        "gmail_message_id",
        "gmail_thread_id",
        "telegram_chat_id",
        "telegram_message_id",
        "telegram_sent_at",
        "last_reminded_at",
        "telegram_error",
        "taken_by",
        "taken_by_label",
        "taken_at",
        "created_at",
        "updated_at",
        "processed_at",
    )
    actions = (
        "mark_as_in_work",
        "mark_as_ignored",
        "mark_as_unread",
        "send_test_telegram_alert",
        "close_case_by_listing",
    )
    fieldsets = (
        (
            _("Lead"),
            {
                "description": _(
                    "A short Kleinanzeigen event card: who wrote, which listing "
                    "it belongs to, and what needs attention."
                ),
                "fields": (
                    "mailbox",
                    "buyer_name",
                    "listing_title",
                    "listing_id",
                    "message_text",
                ),
            },
        ),
        (
            _("Status and priority"),
            {
                "description": _(
                    "Operational lead classification: event type, current handling "
                    "status, priority, and risk or quality flags."
                ),
                "fields": (
                    "event_type",
                    "alert_status",
                    "taken_by",
                    "taken_by_label",
                    "taken_at",
                    "priority",
                    "flags",
                    "classification_reason",
                ),
            },
        ),
        (
            _("Parsing"),
            {
                "description": _(
                    "Parser diagnostics. Partial means the email was handled, but "
                    "some fields could not be extracted."
                ),
                "fields": ("parse_status", "parse_error", "normalized_body"),
            },
        ),
        (
            _("Source email"),
            {
                "description": _(
                    "Raw Gmail data is kept for parser debugging and case rechecks."
                ),
                "fields": ("subject", "raw_subject", "raw_body"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Technical fields"),
            {
                "description": _(
                    "Gmail identifiers and timestamps for deduplication and "
                    "processing audit."
                ),
                "fields": (
                    "gmail_message_id",
                    "gmail_thread_id",
                    "telegram_chat_id",
                    "telegram_message_id",
                    "telegram_sent_at",
                    "last_reminded_at",
                    "telegram_error",
                    "received_at",
                    "processed_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description=_("Lead"), ordering="listing_title")
    def display_title(self, obj):
        return obj.listing_title or obj.subject or obj.get_event_type_display()

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("mailbox", "taken_by")
            .prefetch_related("flags")
            .annotate(
                risk_flags_count=Count(
                    "flags",
                    filter=Q(flags__category=LeadFlag.Category.RISK),
                )
            )
        )

    @admin.display(description=_("Type"), ordering="event_type")
    def event_type_badge(self, obj):
        css_by_type = {
            MarketplaceAlert.EventType.BUYER_MESSAGE: "text-bg-primary",
            MarketplaceAlert.EventType.LISTING_EXPIRING: "text-bg-warning",
            MarketplaceAlert.EventType.SYSTEM_NOTICE: "text-bg-info",
            MarketplaceAlert.EventType.NOISE: "text-bg-secondary",
        }
        return status_badge(
            obj.get_event_type_display(),
            css_by_type.get(obj.event_type, "text-bg-secondary"),
        )

    @admin.display(description=_("Status"), ordering="alert_status")
    def status_badge(self, obj):
        css_by_status = {
            MarketplaceAlert.AlertStatus.UNREAD: "text-bg-danger",
            MarketplaceAlert.AlertStatus.IN_WORK: "text-bg-warning",
            MarketplaceAlert.AlertStatus.IGNORED: "text-bg-secondary",
        }
        return status_badge(
            obj.get_alert_status_display(),
            css_by_status.get(obj.alert_status, "text-bg-secondary"),
        )

    @admin.display(description=_("Owner"), ordering="taken_by_label")
    def taken_by_display(self, obj):
        if obj.taken_by:
            return obj.taken_by.get_full_name() or obj.taken_by.get_username()
        return obj.taken_by_label or "—"

    @admin.display(description=_("Priority"), ordering="priority")
    def priority_badge(self, obj):
        css_by_priority = {
            MarketplaceAlert.Priority.LOW: "text-bg-secondary",
            MarketplaceAlert.Priority.NORMAL: "text-bg-info",
            MarketplaceAlert.Priority.HIGH: "text-bg-warning",
            MarketplaceAlert.Priority.URGENT: "text-bg-danger",
        }
        return status_badge(
            obj.get_priority_display(),
            css_by_priority.get(obj.priority, "text-bg-secondary"),
        )

    @admin.display(description=_("Risk"))
    def risk_badge(self, obj):
        risk_count = getattr(obj, "risk_flags_count", 0)
        if risk_count:
            return status_badge(_("risk: %(count)s") % {"count": risk_count}, "text-bg-danger")
        return status_badge(_("none"), "text-bg-success")

    @admin.display(description=_("Attention"))
    def needs_attention_badge(self, obj):
        if (
            obj.alert_status == MarketplaceAlert.AlertStatus.UNREAD
            or obj.priority
            in [MarketplaceAlert.Priority.HIGH, MarketplaceAlert.Priority.URGENT]
            or obj.parse_status
            in [MarketplaceAlert.ParseStatus.ERROR, MarketplaceAlert.ParseStatus.PARTIAL]
            or obj.telegram_error
            or obj.mailbox.connection_status == MailboxAccount.ConnectionStatus.ERROR
        ):
            return status_badge(_("needed"), "text-bg-danger")
        return status_badge(_("ok"), "text-bg-success")

    @admin.display(description=_("Parsing"), ordering="parse_status")
    def parse_status_badge(self, obj):
        css_by_status = {
            MarketplaceAlert.ParseStatus.SUCCESS: "text-bg-success",
            MarketplaceAlert.ParseStatus.PARTIAL: "text-bg-warning",
            MarketplaceAlert.ParseStatus.ERROR: "text-bg-danger",
            MarketplaceAlert.ParseStatus.SKIPPED: "text-bg-secondary",
        }
        return status_badge(
            obj.get_parse_status_display(),
            css_by_status.get(obj.parse_status, "text-bg-secondary"),
        )

    @admin.action(description=_("Mark as in work"))
    def mark_as_in_work(self, request, queryset):
        label = request.user.get_full_name() or request.user.get_username()
        updated = queryset.update(
            alert_status=MarketplaceAlert.AlertStatus.IN_WORK,
            taken_by=request.user,
            taken_by_label=label,
            taken_at=timezone.now(),
        )
        self.message_user(request, _("Leads moved to in work: %(count)s.") % {"count": updated})

    @admin.action(description=_("Mark as ignored"))
    def mark_as_ignored(self, request, queryset):
        updated = queryset.update(alert_status=MarketplaceAlert.AlertStatus.IGNORED)
        self.message_user(request, _("Leads marked ignored: %(count)s.") % {"count": updated})

    @admin.action(description=_("Return to new"))
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
            taken_by=None,
            taken_by_label="",
            taken_at=None,
        )
        self.message_user(request, _("Leads returned to new: %(count)s.") % {"count": updated})

    @admin.action(description=_("Send test Telegram alert"))
    def send_test_telegram_alert(self, request, queryset):
        from alerts.admin import send_telegram_alert

        sent = 0
        failed = 0

        for alert in queryset[:10]:
            try:
                send_telegram_alert(alert)
            except Exception as exc:
                failed += 1
                self.message_user(
                    request,
                    _("Could not send Telegram alert #%(id)s: %(error)s")
                    % {"id": alert.id, "error": exc},
                    level=messages.ERROR,
                )
                continue

            sent += 1

        if sent:
            self.message_user(request, _("Test Telegram alerts sent: %(count)s.") % {"count": sent})

        if failed:
            self.message_user(
                request,
                _("Telegram send errors: %(count)s.") % {"count": failed},
                level=messages.WARNING,
            )

    @admin.action(description=_("Case closed: delete leads by listing_id"))
    def close_case_by_listing(self, request, queryset):
        result = close_cases_for_alerts(queryset)
        if result.selected_cases == 0:
            self.message_user(
                request,
                _("No leads with listing_id were found for closing."),
                level="warning",
            )
            return

        self.message_user(
            request,
            (
                _("Closed cases: %(cases)s; deleted leads: %(leads)s.")
                % {
                    "cases": result.selected_cases,
                    "leads": result.deleted_alerts,
                }
            ),
        )


@admin.register(NoiseAlert)
class NoiseAlertAdmin(MarketplaceAlertAdmin):
    list_display = (
        "display_title",
        "mailbox",
        "status_badge",
        "parse_status_badge",
        "received_at",
        "created_at",
    )
    list_filter = ("mailbox", "alert_status", "parse_status", "received_at")
    actions = (
        "mark_as_buyer_message",
        "mark_as_system_notice",
        "mark_as_listing_expiring",
        "mark_as_ignored",
        "mark_as_unread",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            event_type=MarketplaceAlert.EventType.NOISE
        )

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("This is a useful lead: move to leads"))
    def mark_as_buyer_message(self, request, queryset):
        updated = queryset.update(
            event_type=MarketplaceAlert.EventType.BUYER_MESSAGE,
            parse_status=MarketplaceAlert.ParseStatus.PARTIAL,
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        )
        self.message_user(request, _("Emails moved to leads: %(count)s.") % {"count": updated})

    @admin.action(description=_("This is a service email"))
    def mark_as_system_notice(self, request, queryset):
        updated = queryset.update(
            event_type=MarketplaceAlert.EventType.SYSTEM_NOTICE,
            parse_status=MarketplaceAlert.ParseStatus.SUCCESS,
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        )
        self.message_user(request, _("Emails moved to service messages: %(count)s.") % {"count": updated})

    @admin.action(description=_("This is a listing event"))
    def mark_as_listing_expiring(self, request, queryset):
        updated = queryset.update(
            event_type=MarketplaceAlert.EventType.LISTING_EXPIRING,
            parse_status=MarketplaceAlert.ParseStatus.SUCCESS,
            alert_status=MarketplaceAlert.AlertStatus.UNREAD,
        )
        self.message_user(
            request,
            _("Emails moved to listing events: %(count)s.") % {"count": updated},
        )
