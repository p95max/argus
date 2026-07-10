from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from ..models import (
    ArgusSettings,
    LanguageCode,
    LeadFlag,
    ProcessedEmail,
    ServiceEvent,
    TelegramSettings,
)


class ArgusSettingsAdminForm(forms.ModelForm):
    language_code = forms.ChoiceField(
        label=_("Interface language"),
        choices=(
            (LanguageCode.ENGLISH, _("English - default")),
            (LanguageCode.GERMAN, _("German - Deutsch")),
            (LanguageCode.RUSSIAN, _("Russian - Русский")),
        ),
        widget=forms.RadioSelect,
        help_text=_(
            "This language is used globally in Django Admin, the mobile panel, "
            "and operational UI. Only superusers can change it."
        ),
    )

    class Meta:
        model = ArgusSettings
        fields = ("language_code",)


@admin.register(ArgusSettings)
class ArgusSettingsAdmin(admin.ModelAdmin):
    form = ArgusSettingsAdminForm
    list_display = ("id", "language_code", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            _("Interface language"),
            {
                "description": _(
                    "Global language for Argus. Only superusers can change it. "
                    "There is no public language switcher."
                ),
                "fields": ("language_code",),
            },
        ),
        (
            _("Audit"),
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser and not ArgusSettings.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


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
                "description": _(
                    "When quiet hours are enabled, regular Telegram alerts are not "
                    "sent during the configured window. The default window is "
                    "22:00-07:00, but the feature is disabled by default."
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
            _("Lead flag"),
            {
                "description": _(
                    "Flags explain priority: a good signal, a risk, or low lead quality."
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
            _("Deduplication"),
            {
                "description": _(
                    "Technical record: this email has already been processed and "
                    "must not create a duplicate alert."
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
            _("Time"),
            {
                "description": _("When the email arrived and when Argus processed it."),
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
