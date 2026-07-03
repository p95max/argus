from django.contrib import admin
from django.db.models import Q
from django.utils.html import format_html

from .models import LeadFlag, MailboxAccount, MarketplaceAlert, ProcessedEmail
from .permissions import can_manage_mailboxes, can_view_mailbox_operations


def status_badge(text, css_class):
    return format_html('<span class="badge {}">{}</span>', css_class, text)


@admin.register(MailboxAccount)
class MailboxAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "active_badge", "connection_badge", "last_checked_at")
    list_filter = ("is_active", "connection_status")
    search_fields = ("email", "name")
    readonly_fields = ("created_at", "updated_at")
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
                "description": "Фильтр писем и состояние подключения. Приватные OAuth-данные здесь не храним.",
                "fields": ("gmail_search_query", "connection_status"),
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

    def has_view_permission(self, request, obj=None):
        return can_view_mailbox_operations(request.user)

    def has_add_permission(self, request):
        return can_manage_mailboxes(request.user)

    def has_change_permission(self, request, obj=None):
        return can_manage_mailboxes(request.user)

    def has_delete_permission(self, request, obj=None):
        return can_manage_mailboxes(request.user)

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
