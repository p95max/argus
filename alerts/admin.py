from django.contrib import admin

from .models import LeadFlag, MailboxAccount, MarketplaceAlert, ProcessedEmail


@admin.register(MailboxAccount)
class MailboxAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "is_active", "connection_status", "last_checked_at")
    list_filter = ("is_active", "connection_status")
    search_fields = ("email", "name")


@admin.register(LeadFlag)
class LeadFlagAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")


@admin.register(MarketplaceAlert)
class MarketplaceAlertAdmin(admin.ModelAdmin):
    list_display = (
        "listing_title",
        "buyer_name",
        "mailbox",
        "event_type",
        "alert_status",
        "priority",
        "received_at",
    )
    list_filter = ("alert_status", "priority", "event_type", "parse_status", "mailbox")
    search_fields = ("listing_title", "buyer_name", "subject", "message_text", "listing_id")
    filter_horizontal = ("flags",)


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = ("gmail_message_id", "mailbox", "subject", "received_at", "processed_at")
    list_filter = ("mailbox", "processed_at")
    search_fields = ("gmail_message_id", "gmail_thread_id", "subject")
    readonly_fields = ("created_at", "updated_at")
