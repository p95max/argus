from django.contrib import admin

from ..models import LeadFlag, ProcessedEmail, ServiceEvent, TelegramSettings


@admin.register(TelegramSettings)
class TelegramSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "quiet_hours_enabled",
        "quiet_hours_start",
        "quiet_hours_end",
        "allow_urgent_during_quiet_hours",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Quiet hours",
            {
                "description": (
                    "Когда quiet hours включены, обычные Telegram alerts не отправляются "
                    "в заданное окно. По умолчанию окно 22:00-07:00, но функция выключена."
                ),
                "fields": (
                    "quiet_hours_enabled",
                    "quiet_hours_start",
                    "quiet_hours_end",
                    "allow_urgent_during_quiet_hours",
                ),
            },
        ),
        (
            "Audit",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_add_permission(self, request):
        if TelegramSettings.objects.exists():
            return False
        return super().has_add_permission(request)


@admin.register(LeadFlag)
class LeadFlagAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")
    fieldsets = (
        (
            "Флаг обращения",
            {
                "description": (
                    "Флаги помогают объяснить приоритет: хороший сигнал, риск "
                    "или низкое качество обращения."
                ),
                "fields": (
                    "code",
                    "name",
                    "category",
                    "is_active",
                    "description",
                ),
            },
        ),
    )


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = (
        "gmail_message_id",
        "mailbox",
        "subject",
        "received_at",
        "processed_at",
    )
    list_filter = ("mailbox", "processed_at")
    search_fields = ("gmail_message_id", "gmail_thread_id", "subject")
    readonly_fields = (
        "mailbox",
        "gmail_message_id",
        "gmail_thread_id",
        "subject",
        "received_at",
        "processed_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Дедупликация",
            {
                "description": (
                    "Техническая запись: письмо уже было обработано и не должно "
                    "создать дубль alert."
                ),
                "fields": (
                    "mailbox",
                    "gmail_message_id",
                    "gmail_thread_id",
                    "subject",
                ),
            },
        ),
        (
            "Время",
            {
                "description": "Когда письмо пришло и когда Argus его обработал.",
                "fields": (
                    "received_at",
                    "processed_at",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ServiceEvent)
class ServiceEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event_type",
        "severity",
        "status",
        "title",
        "mailbox",
        "alert",
        "occurrences",
        "telegram_sent_at",
    )
    list_filter = ("event_type", "severity", "status", "source", "mailbox")
    search_fields = ("title", "details", "fingerprint", "mailbox__email")
    readonly_fields = (
        "mailbox",
        "alert",
        "event_type",
        "severity",
        "status",
        "source",
        "title",
        "details",
        "fingerprint",
        "occurrences",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
        "telegram_sent_at",
        "telegram_error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False