from datetime import time

from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        abstract = True


class MailboxAccount(TimestampedModel):
    class ConnectionStatus(models.TextChoices):
        NOT_CONNECTED = "not_connected", "Не подключен"
        CONNECTED = "connected", "Подключен"
        ERROR = "error", "Ошибка"
        DISABLED = "disabled", "Отключен"

    name = models.CharField("название", max_length=120)
    email = models.EmailField("email", unique=True)
    is_active = models.BooleanField("активен", default=True)
    gmail_search_query = models.CharField(
        "Gmail search query",
        max_length=500,
        default="from:(kleinanzeigen.de)",
        blank=True,
    )

    gmail_connected_email = models.EmailField("подключенный Gmail", blank=True)
    gmail_oauth_token = models.TextField("Gmail OAuth token JSON", blank=True)
    gmail_oauth_connected_at = models.DateTimeField("Gmail подключен", null=True, blank=True)
    gmail_oauth_last_refresh_at = models.DateTimeField("последнее обновление Gmail token", null=True, blank=True)
    gmail_oauth_error = models.TextField("ошибка Gmail OAuth", blank=True)

    connection_status = models.CharField(
        "статус подключения",
        max_length=32,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.NOT_CONNECTED,
    )
    last_checked_at = models.DateTimeField("последняя проверка", null=True, blank=True)
    last_success_at = models.DateTimeField("последний успех", null=True, blank=True)
    last_error = models.TextField("последняя ошибка", blank=True)

    class Meta:
        ordering = ["email"]
        verbose_name = "почтовый ящик"
        verbose_name_plural = "почтовые ящики"

    def __str__(self):
        return f"{self.name} <{self.email}>"


class LeadFlag(TimestampedModel):
    class Category(models.TextChoices):
        POSITIVE = "positive", "Позитивный сигнал"
        RISK = "risk", "Риск"
        LOW_QUALITY = "low_quality", "Низкое качество"
        SYSTEM = "system", "Системный"

    code = models.SlugField("код", max_length=80, unique=True)
    name = models.CharField("название", max_length=120)
    category = models.CharField(
        "категория",
        max_length=32,
        choices=Category.choices,
        default=Category.POSITIVE,
    )
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name = "флаг обращения"
        verbose_name_plural = "флаги обращений"

    def __str__(self):
        return self.name


class MarketplaceAlert(TimestampedModel):
    class EventType(models.TextChoices):
        BUYER_MESSAGE = "buyer_message", "Сообщение покупателя"
        LISTING_EXPIRING = "listing_expiring", "Объявление истекает"
        SYSTEM_NOTICE = "system_notice", "Системное уведомление"
        NOISE = "noise", "Шум"

    class AlertStatus(models.TextChoices):
        UNREAD = "unread", "Новое"
        IN_WORK = "in_work", "В работе"
        IGNORED = "ignored", "Игнор"

    class Priority(models.TextChoices):
        LOW = "low", "Низкий"
        NORMAL = "normal", "Обычный"
        HIGH = "high", "Высокий"
        URGENT = "urgent", "Срочный"

    class ParseStatus(models.TextChoices):
        SUCCESS = "success", "Успешно"
        PARTIAL = "partial", "Частично"
        ERROR = "error", "Ошибка"
        SKIPPED = "skipped", "Пропущено"

    mailbox = models.ForeignKey(
        MailboxAccount,
        verbose_name="почтовый ящик",
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    flags = models.ManyToManyField(LeadFlag, verbose_name="флаги", blank=True, related_name="alerts")

    event_type = models.CharField(
        "тип события",
        max_length=32,
        choices=EventType.choices,
        default=EventType.BUYER_MESSAGE,
    )
    alert_status = models.CharField(
        "статус",
        max_length=32,
        choices=AlertStatus.choices,
        default=AlertStatus.UNREAD,
    )
    priority = models.CharField(
        "приоритет",
        max_length=32,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    parse_status = models.CharField(
        "статус парсинга",
        max_length=32,
        choices=ParseStatus.choices,
        default=ParseStatus.SUCCESS,
    )
    parse_error = models.TextField("ошибка парсинга", blank=True)
    classification_reason = models.TextField("объяснение классификации", blank=True)

    listing_id = models.CharField("ID объявления", max_length=120, blank=True)
    listing_title = models.CharField("название объявления", max_length=255, blank=True)
    buyer_name = models.CharField("покупатель", max_length=150, blank=True)
    subject = models.CharField("тема", max_length=500, blank=True)
    message_text = models.TextField("сообщение", blank=True)
    raw_subject = models.CharField("исходная тема", max_length=500, blank=True)
    raw_body = models.TextField("исходное тело письма", blank=True)
    normalized_body = models.TextField("нормализованное тело письма", blank=True)

    gmail_message_id = models.CharField("Gmail message ID", max_length=255, blank=True)
    gmail_thread_id = models.CharField("Gmail thread ID", max_length=255, blank=True)
    telegram_chat_id = models.CharField("Telegram chat ID", max_length=64, blank=True)
    telegram_message_id = models.CharField("Telegram message ID", max_length=64, blank=True)
    telegram_sent_at = models.DateTimeField("отправлено в Telegram", null=True, blank=True)
    telegram_error = models.TextField("ошибка Telegram", blank=True)
    last_reminded_at = models.DateTimeField("последний reminder", null=True, blank=True)
    received_at = models.DateTimeField("получено", null=True, blank=True)
    processed_at = models.DateTimeField("обработано", default=timezone.now)

    class Meta:
        ordering = ["-received_at", "-created_at"]
        indexes = [
            models.Index(fields=["alert_status", "priority"]),
            models.Index(fields=["event_type"]),
            models.Index(fields=["listing_id"]),
        ]
        verbose_name = "обращение"
        verbose_name_plural = "обращения"

    def __str__(self):
        title = self.listing_title or self.subject or self.get_event_type_display()
        return f"{title} ({self.get_alert_status_display()})"


class ProcessedEmail(TimestampedModel):
    mailbox = models.ForeignKey(
        MailboxAccount,
        verbose_name="почтовый ящик",
        on_delete=models.CASCADE,
        related_name="processed_emails",
    )
    gmail_message_id = models.CharField("Gmail message ID", max_length=255)
    gmail_thread_id = models.CharField("Gmail thread ID", max_length=255, blank=True)
    subject = models.CharField("тема", max_length=500, blank=True)
    received_at = models.DateTimeField("получено", null=True, blank=True)
    processed_at = models.DateTimeField("обработано", default=timezone.now)

    class Meta:
        ordering = ["-processed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "gmail_message_id"],
                name="unique_processed_email_per_mailbox",
            ),
        ]
        verbose_name = "обработанное письмо"
        verbose_name_plural = "обработанные письма"

    def __str__(self):
        return f"{self.mailbox.email}: {self.gmail_message_id}"


class ServiceEvent(TimestampedModel):
    class EventType(models.TextChoices):
        MAILBOX_ERROR = "mailbox_error", "Ошибка mailbox"
        PARSER_ERROR = "parser_error", "Ошибка parser"
        TELEGRAM_SEND_ERROR = "telegram_send_error", "Ошибка Telegram send"
        RECOVERY = "recovery", "Восстановление"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Открыто"
        RECOVERED = "recovered", "Восстановлено"

    mailbox = models.ForeignKey(
        MailboxAccount,
        verbose_name="почтовый ящик",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_events",
    )
    alert = models.ForeignKey(
        MarketplaceAlert,
        verbose_name="обращение",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_events",
    )
    event_type = models.CharField("тип события", max_length=32, choices=EventType.choices)
    severity = models.CharField("важность", max_length=16, choices=Severity.choices)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.OPEN)
    source = models.CharField("источник", max_length=80, blank=True)
    title = models.CharField("заголовок", max_length=255)
    details = models.TextField("детали", blank=True)
    fingerprint = models.CharField("fingerprint", max_length=255, db_index=True)
    occurrences = models.PositiveIntegerField("повторы", default=1)
    first_seen_at = models.DateTimeField("первое событие", default=timezone.now)
    last_seen_at = models.DateTimeField("последнее событие", default=timezone.now)
    resolved_at = models.DateTimeField("восстановлено", null=True, blank=True)
    telegram_sent_at = models.DateTimeField("отправлено в Telegram", null=True, blank=True)
    telegram_error = models.TextField("ошибка Telegram", blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]
        indexes = [
            models.Index(fields=["event_type", "status"]),
            models.Index(fields=["severity", "status"]),
            models.Index(fields=["fingerprint", "status"]),
        ]
        verbose_name = "service event"
        verbose_name_plural = "service events"

    def __str__(self):
        return f"{self.get_event_type_display()}: {self.title}"


class TelegramSettings(TimestampedModel):
    quiet_hours_enabled = models.BooleanField("quiet hours включены", default=False)
    quiet_hours_start = models.TimeField("quiet hours начало", default=time(22, 0))
    quiet_hours_end = models.TimeField("quiet hours конец", default=time(7, 0))
    allow_urgent_during_quiet_hours = models.BooleanField(
        "отправлять срочные alerts в quiet hours",
        default=False,
    )

    class Meta:
        verbose_name = "настройки Telegram"
        verbose_name_plural = "настройки Telegram"

    def __str__(self):
        status = "включены" if self.quiet_hours_enabled else "выключены"
        return f"Telegram settings: quiet hours {status}"

    @classmethod
    def load(cls):
        settings = cls.objects.order_by("id").first()
        if settings:
            return settings
        return cls.objects.create()
