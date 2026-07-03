from django.contrib import admin

from .models import LeadFlag, MailboxAccount, MarketplaceAlert, ProcessedEmail


@admin.register(MailboxAccount)
class MailboxAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "is_active", "connection_status", "last_checked_at")
    list_filter = ("is_active", "connection_status")
    search_fields = ("email", "name")
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
                "fields": ("last_checked_at", "last_success_at", "last_error"),
            },
        ),
    )


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
                "fields": ("event_type", "alert_status", "priority", "flags"),
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
                "fields": ("gmail_message_id", "gmail_thread_id", "received_at", "processed_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = ("gmail_message_id", "mailbox", "subject", "received_at", "processed_at")
    list_filter = ("mailbox", "processed_at")
    search_fields = ("gmail_message_id", "gmail_thread_id", "subject")
    readonly_fields = ("created_at", "updated_at")
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
