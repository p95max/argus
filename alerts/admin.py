from django.contrib import admin, messages
from django.db.models import Q
from django.utils.html import format_html
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path, reverse

from .models import LeadFlag, MailboxAccount, MarketplaceAlert, ProcessedEmail, ServiceEvent
from .permissions import can_manage_mailboxes, can_view_mailbox_operations
from .gmail.gmail import check_mailbox
from .gmail.gmail_oauth import build_gmail_authorization_url, complete_gmail_oauth_callback


def status_badge(text, css_class):
    return format_html('<span class="badge {}">{}</span>', css_class, text)


@admin.register(MailboxAccount)
class MailboxAccountAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "name",
        "active_badge",
        "connection_badge",
        "gmail_oauth_badge",
        "last_checked_at",
    )
    list_filter = ("is_active", "connection_status")
    search_fields = ("email", "name", "gmail_connected_email")
    readonly_fields = (
        "gmail_oauth_actions",
        "gmail_connected_email",
        "gmail_oauth_connected_at",
        "gmail_oauth_last_refresh_at",
        "gmail_oauth_error",
        "created_at",
        "updated_at",
    )
    actions = ("enable_mailboxes", "disable_mailboxes")

    fieldsets = (
        (
            "Основное",
            {
                "description": "Почтовый ящик, который Argus будет проверять через Gmail.",
                "fields": ("name", "email", "is_active"),
            },
        ),
        (
            "Gmail",
            {
                "description": (
                    "OAuth подключается из Admin. Токен хранится для конкретного почтового ящика."
                ),
                "fields": (
                    "gmail_search_query",
                    "connection_status",
                    "gmail_oauth_actions",
                    "gmail_connected_email",
                    "gmail_oauth_connected_at",
                    "gmail_oauth_last_refresh_at",
                    "gmail_oauth_error",
                ),
            },
        ),
        (
            "Health",
            {
                "description": "Операционная диагностика: когда ящик проверялся и какая ошибка была последней.",
                "fields": ("last_checked_at", "last_success_at", "last_error", "created_at", "updated_at"),
            },
        ),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:object_id>/gmail/connect/",
                self.admin_site.admin_view(self.gmail_connect_view),
                name="alerts_mailboxaccount_gmail_connect",
            ),
            path(
                "oauth/callback/",
                self.admin_site.admin_view(self.gmail_oauth_callback_view),
                name="alerts_mailboxaccount_gmail_oauth_callback",
            ),
            path(
                "<int:object_id>/gmail/disconnect/",
                self.admin_site.admin_view(self.gmail_disconnect_view),
                name="alerts_mailboxaccount_gmail_disconnect",
            ),
            path(
                "<int:object_id>/gmail/check-now/",
                self.admin_site.admin_view(self.gmail_check_now_view),
                name="alerts_mailboxaccount_gmail_check_now",
            ),
        ]
        return custom_urls + urls

    @admin.display(description="Активен", ordering="is_active")
    def active_badge(self, obj):
        if obj.is_active:
            return status_badge("активен", "text-bg-success")
        return status_badge("выключен", "text-bg-secondary")

    @admin.display(description="Подключение", ordering="connection_status")
    def connection_badge(self, obj):
        css_by_status = {
            MailboxAccount.ConnectionStatus.CONNECTED: "text-bg-success",
            MailboxAccount.ConnectionStatus.ERROR: "text-bg-danger",
            MailboxAccount.ConnectionStatus.DISABLED: "text-bg-secondary",
            MailboxAccount.ConnectionStatus.NOT_CONNECTED: "text-bg-warning",
        }
        return status_badge(obj.get_connection_status_display(), css_by_status.get(obj.connection_status, "text-bg-secondary"))

    @admin.display(description="Gmail OAuth")
    def gmail_oauth_badge(self, obj):
        if obj.gmail_oauth_token:
            return status_badge("OAuth OK", "text-bg-success")
        return status_badge("нет токена", "text-bg-warning")

    @admin.display(description="Gmail действия")
    def gmail_oauth_actions(self, obj):
        if not obj.pk:
            return "Сначала сохраните почтовый ящик."

        connect_url = reverse("admin:alerts_mailboxaccount_gmail_connect", args=[obj.pk])
        disconnect_url = reverse("admin:alerts_mailboxaccount_gmail_disconnect", args=[obj.pk])
        check_url = reverse("admin:alerts_mailboxaccount_gmail_check_now", args=[obj.pk])

        return format_html(
            """
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <a class="btn btn-sm btn-outline-info" href="{}">
                    <i class="fas fa-plug"></i> OAuth
                </a>
                <a class="btn btn-sm btn-outline-success" href="{}">
                    <i class="fas fa-play"></i> Check updates
                </a>
                <a class="btn btn-sm btn-outline-danger" href="{}">
                    <i class="fas fa-times"></i> Disconnect
                </a>
            </div>
            """,
            connect_url,
            check_url,
            disconnect_url,
        )

    def has_view_permission(self, request, obj=None):
        return can_view_mailbox_operations(request.user)

    def has_add_permission(self, request):
        return can_manage_mailboxes(request.user)

    def has_change_permission(self, request, obj=None):
        return can_manage_mailboxes(request.user)

    def has_delete_permission(self, request, obj=None):
        return can_manage_mailboxes(request.user)

    def _require_mailbox_manage_permission(self, request):
        if not can_manage_mailboxes(request.user):
            raise PermissionDenied("You do not have permission to manage Gmail OAuth.")

    def _get_mailbox_or_redirect(self, request, object_id):
        mailbox = self.get_object(request, object_id)
        if mailbox is None:
            messages.error(request, "Почтовый ящик не найден.")
            return None
        return mailbox

    def gmail_connect_view(self, request, object_id):
        self._require_mailbox_manage_permission(request)
        mailbox = self._get_mailbox_or_redirect(request, object_id)
        if mailbox is None:
            return redirect("admin:alerts_mailboxaccount_changelist")

        try:
            authorization_url = build_gmail_authorization_url(request, mailbox)
        except Exception as exc:
            mailbox.connection_status = MailboxAccount.ConnectionStatus.ERROR
            mailbox.gmail_oauth_error = str(exc)
            mailbox.last_error = str(exc)
            mailbox.save(
                update_fields=[
                    "connection_status",
                    "gmail_oauth_error",
                    "last_error",
                    "updated_at",
                ]
            )
            messages.error(request, f"Gmail OAuth start failed: {exc}")
            return redirect("admin:alerts_mailboxaccount_change", object_id)

        return redirect(authorization_url)

    def gmail_oauth_callback_view(self, request):
        self._require_mailbox_manage_permission(request)

        try:
            result = complete_gmail_oauth_callback(request)
        except Exception as exc:
            messages.error(request, f"Gmail OAuth failed: {exc}")
            return redirect("admin:alerts_mailboxaccount_changelist")

        messages.success(
            request,
            f"Gmail подключен: {result.google_email} для {result.mailbox.email}.",
        )
        return redirect("admin:alerts_mailboxaccount_change", result.mailbox.id)

    def gmail_disconnect_view(self, request, object_id):
        self._require_mailbox_manage_permission(request)
        mailbox = self._get_mailbox_or_redirect(request, object_id)
        if mailbox is None:
            return redirect("admin:alerts_mailboxaccount_changelist")

        mailbox.gmail_connected_email = ""
        mailbox.gmail_oauth_token = ""
        mailbox.gmail_oauth_connected_at = None
        mailbox.gmail_oauth_last_refresh_at = None
        mailbox.gmail_oauth_error = ""
        mailbox.connection_status = MailboxAccount.ConnectionStatus.NOT_CONNECTED
        mailbox.last_error = ""
        mailbox.save(
            update_fields=[
                "gmail_connected_email",
                "gmail_oauth_token",
                "gmail_oauth_connected_at",
                "gmail_oauth_last_refresh_at",
                "gmail_oauth_error",
                "connection_status",
                "last_error",
                "updated_at",
            ]
        )

        messages.success(request, f"Gmail отключен для {mailbox.email}.")
        return redirect("admin:alerts_mailboxaccount_change", mailbox.id)

    def gmail_check_now_view(self, request, object_id):
        self._require_mailbox_manage_permission(request)
        mailbox = self._get_mailbox_or_redirect(request, object_id)
        if mailbox is None:
            return redirect("admin:alerts_mailboxaccount_changelist")

        try:
            result = check_mailbox(mailbox)
        except Exception as exc:
            messages.error(request, f"Gmail check failed for {mailbox.email}: {exc}")
            return redirect("admin:alerts_mailboxaccount_change", mailbox.id)

        messages.success(
            request,
            (
                f"Gmail check completed for {mailbox.email}: "
                f"fetched {result.fetched}, created {result.created}, duplicates {result.duplicates}."
            ),
        )
        return redirect("admin:alerts_mailboxaccount_change", mailbox.id)

    @admin.action(description="Включить выбранные ящики")
    def enable_mailboxes(self, request, queryset):
        updated = queryset.update(is_active=True, connection_status=MailboxAccount.ConnectionStatus.NOT_CONNECTED)
        self.message_user(request, f"Включено ящиков: {updated}.")

    @admin.action(description="Отключить выбранные ящики")
    def disable_mailboxes(self, request, queryset):
        updated = queryset.update(is_active=False, connection_status=MailboxAccount.ConnectionStatus.DISABLED)
        self.message_user(request, f"Отключено ящиков: {updated}.")


@admin.register(LeadFlag)
class LeadFlagAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")
    fieldsets = (
        (
            "Флаг обращения",
            {
                "description": "Флаги помогают объяснить приоритет: хороший сигнал, риск или низкое качество обращения.",
                "fields": ("code", "name", "category", "is_active", "description"),
            },
        ),
    )


@admin.register(MarketplaceAlert)
class MarketplaceAlertAdmin(admin.ModelAdmin):
    list_display = (
        "display_title",
        "buyer_name",
        "mailbox",
        "event_type_badge",
        "status_badge",
        "priority_badge",
        "parse_status_badge",
        "received_at",
    )
    list_filter = ("mailbox", "alert_status", "priority", "event_type", "parse_status", "flags")
    search_fields = ("listing_title", "buyer_name", "subject", "message_text", "listing_id")
    filter_horizontal = ("flags",)
    readonly_fields = (
        "gmail_message_id",
        "gmail_thread_id",
        "telegram_chat_id",
        "telegram_message_id",
        "telegram_sent_at",
        "telegram_error",
        "created_at",
        "updated_at",
        "processed_at",
    )
    actions = ("mark_as_in_work", "mark_as_ignored", "mark_as_unread", "close_case_by_listing")
    fieldsets = (
        (
            "Обращение",
            {
                "description": (
                    "Краткая карточка события из Kleinanzeigen. Здесь видно, кто написал, "
                    "по какому объявлению и что требует внимания."
                ),
                "fields": ("mailbox", "buyer_name", "listing_title", "listing_id", "message_text"),
            },
        ),
        (
            "Статус и приоритет",
            {
                "description": (
                    "Рабочая классификация обращения: тип события, текущий статус обработки, "
                    "важность и флаги риска/качества."
                ),
                "fields": ("event_type", "alert_status", "priority", "flags", "classification_reason"),
            },
        ),
        (
            "Парсинг",
            {
                "description": (
                    "Диагностика результата парсера. Partial означает, что письмо обработано, "
                    "но часть полей не удалось извлечь."
                ),
                "fields": ("parse_status", "parse_error", "normalized_body"),
            },
        ),
        (
            "Исходное письмо",
            {
                "description": "Сырые данные Gmail нужны для отладки parser logic и повторной проверки кейса.",
                "fields": ("subject", "raw_subject", "raw_body"),
                "classes": ("collapse",),
            },
        ),
        (
            "Технические поля",
            {
                "description": "Идентификаторы Gmail и timestamps для дедупликации и аудита обработки.",
                "fields": (
                    "gmail_message_id",
                    "gmail_thread_id",
                    "telegram_chat_id",
                    "telegram_message_id",
                    "telegram_sent_at",
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

    @admin.display(description="Обращение", ordering="listing_title")
    def display_title(self, obj):
        return obj.listing_title or obj.subject or obj.get_event_type_display()

    @admin.display(description="Тип", ordering="event_type")
    def event_type_badge(self, obj):
        css_by_type = {
            MarketplaceAlert.EventType.BUYER_MESSAGE: "text-bg-primary",
            MarketplaceAlert.EventType.LISTING_EXPIRING: "text-bg-warning",
            MarketplaceAlert.EventType.SYSTEM_NOTICE: "text-bg-info",
            MarketplaceAlert.EventType.NOISE: "text-bg-secondary",
        }
        return status_badge(obj.get_event_type_display(), css_by_type.get(obj.event_type, "text-bg-secondary"))

    @admin.display(description="Статус", ordering="alert_status")
    def status_badge(self, obj):
        css_by_status = {
            MarketplaceAlert.AlertStatus.UNREAD: "text-bg-danger",
            MarketplaceAlert.AlertStatus.IN_WORK: "text-bg-warning",
            MarketplaceAlert.AlertStatus.IGNORED: "text-bg-secondary",
        }
        return status_badge(obj.get_alert_status_display(), css_by_status.get(obj.alert_status, "text-bg-secondary"))

    @admin.display(description="Приоритет", ordering="priority")
    def priority_badge(self, obj):
        css_by_priority = {
            MarketplaceAlert.Priority.LOW: "text-bg-secondary",
            MarketplaceAlert.Priority.NORMAL: "text-bg-info",
            MarketplaceAlert.Priority.HIGH: "text-bg-warning",
            MarketplaceAlert.Priority.URGENT: "text-bg-danger",
        }
        return status_badge(obj.get_priority_display(), css_by_priority.get(obj.priority, "text-bg-secondary"))

    @admin.display(description="Парсинг", ordering="parse_status")
    def parse_status_badge(self, obj):
        css_by_status = {
            MarketplaceAlert.ParseStatus.SUCCESS: "text-bg-success",
            MarketplaceAlert.ParseStatus.PARTIAL: "text-bg-warning",
            MarketplaceAlert.ParseStatus.ERROR: "text-bg-danger",
            MarketplaceAlert.ParseStatus.SKIPPED: "text-bg-secondary",
        }
        return status_badge(obj.get_parse_status_display(), css_by_status.get(obj.parse_status, "text-bg-secondary"))

    @admin.action(description="Пометить как в работе")
    def mark_as_in_work(self, request, queryset):
        updated = queryset.update(alert_status=MarketplaceAlert.AlertStatus.IN_WORK)
        self.message_user(request, f"Обращений переведено в работу: {updated}.")

    @admin.action(description="Пометить как игнор")
    def mark_as_ignored(self, request, queryset):
        updated = queryset.update(alert_status=MarketplaceAlert.AlertStatus.IGNORED)
        self.message_user(request, f"Обращений помечено как игнор: {updated}.")

    @admin.action(description="Вернуть в новые")
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(alert_status=MarketplaceAlert.AlertStatus.UNREAD)
        self.message_user(request, f"Обращений возвращено в новые: {updated}.")

    @admin.action(description="Кейс закрыт: удалить обращения по listing_id")
    def close_case_by_listing(self, request, queryset):
        case_filters = Q()
        selected_cases = 0
        for mailbox_id, listing_id in queryset.exclude(listing_id="").values_list("mailbox_id", "listing_id").distinct():
            case_filters |= Q(mailbox_id=mailbox_id, listing_id=listing_id)
            selected_cases += 1

        if not case_filters:
            self.message_user(request, "Не найдено обращений с listing_id для закрытия.", level="warning")
            return

        deleted_count, _ = MarketplaceAlert.objects.filter(case_filters).delete()
        self.message_user(request, f"Закрыто кейсов: {selected_cases}; удалено обращений: {deleted_count}.")


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = ("gmail_message_id", "mailbox", "subject", "received_at", "processed_at")
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
                    "Техническая запись: письмо уже было обработано и не должно создать дубль alert."
                ),
                "fields": ("mailbox", "gmail_message_id", "gmail_thread_id", "subject"),
            },
        ),
        (
            "Время",
            {
                "description": "Когда письмо пришло и когда Argus его обработал.",
                "fields": ("received_at", "processed_at", "created_at", "updated_at"),
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
