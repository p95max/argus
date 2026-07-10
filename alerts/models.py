from datetime import time
import re

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class LanguageCode(models.TextChoices):
    ENGLISH = "en", _("English")
    GERMAN = "de", _("German")
    RUSSIAN = "ru", _("Russian")


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class MailboxAccount(TimestampedModel):
    class ConnectionStatus(models.TextChoices):
        NOT_CONNECTED = "not_connected", _("Not connected")
        CONNECTED = "connected", _("Connected")
        ERROR = "error", _("Error")
        DISABLED = "disabled", _("Disabled")

    class FetchPeriod(models.TextChoices):
        TODAY = "today", _("Today")
        LAST_7_DAYS = "last_7_days", _("Last 7 days")
        ALL = "all", _("No date limit")

    name = models.CharField(_("name"), max_length=120)
    email = models.EmailField("email", unique=True, blank=True, null=True)
    is_active = models.BooleanField(_("active"), default=True)
    gmail_search_query = models.CharField(
        "Gmail search query",
        max_length=500,
        default="from:(kleinanzeigen.de)",
        blank=True,
    )
    fetch_period = models.CharField(
        _("Email fetch period"),
        max_length=20,
        choices=FetchPeriod.choices,
        default=FetchPeriod.TODAY,
        help_text=_("Limits how far back Gmail messages are loaded."),
    )

    gmail_connected_email = models.EmailField(_("connected Gmail"), blank=True)
    gmail_oauth_token = models.TextField("Gmail OAuth token JSON", blank=True)
    gmail_oauth_connected_at = models.DateTimeField(_("Gmail connected at"), null=True, blank=True)
    gmail_oauth_last_refresh_at = models.DateTimeField(_("last Gmail token refresh"), null=True, blank=True)
    gmail_oauth_error = models.TextField(_("Gmail OAuth error"), blank=True)

    connection_status = models.CharField(
        _("connection status"),
        max_length=32,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.NOT_CONNECTED,
    )
    last_checked_at = models.DateTimeField(_("last check"), null=True, blank=True)
    last_success_at = models.DateTimeField(_("last success"), null=True, blank=True)
    last_error = models.TextField(_("last error"), blank=True)

    class Meta:
        ordering = ["email"]
        verbose_name = _("Mailbox")
        verbose_name_plural = _("Mailboxes")

    def build_gmail_search_query(self):
        base_query = re.sub(r"(?:^|\s)newer_than:(?:1d|7d)(?=\s|$)", " ", self.gmail_search_query or "")
        base_query = " ".join(base_query.split())
        period_query = {
            self.FetchPeriod.TODAY: "newer_than:1d",
            self.FetchPeriod.LAST_7_DAYS: "newer_than:7d",
            self.FetchPeriod.ALL: "",
        }.get(self.fetch_period, "newer_than:1d")
        return " ".join(part for part in (base_query, period_query) if part)

    def save(self, *args, **kwargs):
        self.gmail_search_query = self.build_gmail_search_query()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "fetch_period" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"gmail_search_query"}
        super().save(*args, **kwargs)

    def __str__(self):
        if self.email:
            return f"{self.name} <{self.email}>"
        return _("%(name)s <Gmail not connected>") % {"name": self.name}


class LeadFlag(TimestampedModel):
    class Category(models.TextChoices):
        POSITIVE = "positive", _("Positive signal")
        RISK = "risk", _("Risk")
        LOW_QUALITY = "low_quality", _("Low quality")
        SYSTEM = "system", _("System")

    code = models.SlugField(_("code"), max_length=80, unique=True)
    name = models.CharField(_("name"), max_length=120)
    category = models.CharField(
        _("category"),
        max_length=32,
        choices=Category.choices,
        default=Category.POSITIVE,
    )
    description = models.TextField(_("description"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name = _("Lead priority rule")
        verbose_name_plural = _("Lead priority rules")

    def __str__(self):
        return self.name


class MarketplaceAlert(TimestampedModel):
    class EventType(models.TextChoices):
        BUYER_MESSAGE = "buyer_message", _("Buyer message")
        LISTING_EXPIRING = "listing_expiring", _("Listing expiring")
        SYSTEM_NOTICE = "system_notice", _("System notice")
        NOISE = "noise", _("Noise")

    class AlertStatus(models.TextChoices):
        UNREAD = "unread", _("New")
        IN_WORK = "in_work", _("In work")
        IGNORED = "ignored", _("Ignored")
        ARCHIVED = "archived", _("Archived")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    class ParseStatus(models.TextChoices):
        SUCCESS = "success", _("Success")
        PARTIAL = "partial", _("Partial")
        ERROR = "error", _("Error")
        SKIPPED = "skipped", _("Skipped")

    mailbox = models.ForeignKey(
        MailboxAccount,
        verbose_name=_("mailbox"),
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    flags = models.ManyToManyField(LeadFlag, verbose_name=_("flags"), blank=True, related_name="alerts")

    event_type = models.CharField(
        _("event type"),
        max_length=32,
        choices=EventType.choices,
        default=EventType.BUYER_MESSAGE,
    )
    alert_status = models.CharField(
        _("status"),
        max_length=32,
        choices=AlertStatus.choices,
        default=AlertStatus.UNREAD,
    )
    taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("taken by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_alerts_in_work",
    )
    taken_by_label = models.CharField(_("owner label"), max_length=160, blank=True)
    taken_at = models.DateTimeField(_("taken at"), null=True, blank=True)
    priority = models.CharField(
        _("priority"),
        max_length=32,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    parse_status = models.CharField(
        _("parse status"),
        max_length=32,
        choices=ParseStatus.choices,
        default=ParseStatus.SUCCESS,
    )
    parse_error = models.TextField(_("parse error"), blank=True)
    classification_reason = models.TextField(_("classification explanation"), blank=True)

    listing_id = models.CharField(_("listing ID"), max_length=120, blank=True)
    listing_title = models.CharField(_("listing title"), max_length=255, blank=True)
    buyer_name = models.CharField(_("buyer"), max_length=150, blank=True)
    subject = models.CharField(_("subject"), max_length=500, blank=True)
    message_text = models.TextField(_("message"), blank=True)
    raw_subject = models.CharField(_("raw subject"), max_length=500, blank=True)
    raw_body = models.TextField(_("raw email body"), blank=True)
    normalized_body = models.TextField(_("normalized email body"), blank=True)

    gmail_message_id = models.CharField("Gmail message ID", max_length=255, blank=True)
    gmail_thread_id = models.CharField("Gmail thread ID", max_length=255, blank=True)
    telegram_chat_id = models.CharField("Telegram chat ID", max_length=64, blank=True)
    telegram_message_id = models.CharField("Telegram message ID", max_length=64, blank=True)
    telegram_sent_at = models.DateTimeField(_("sent to Telegram at"), null=True, blank=True)
    telegram_error = models.TextField(_("Telegram error"), blank=True)
    last_reminded_at = models.DateTimeField(_("last reminder"), null=True, blank=True)
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    processed_at = models.DateTimeField(_("processed at"), default=timezone.now)

    class Meta:
        ordering = ["-received_at", "-created_at"]
        indexes = [
            models.Index(fields=["alert_status", "priority"]),
            models.Index(fields=["event_type"]),
            models.Index(fields=["listing_id"]),
        ]
        verbose_name = _("Lead")
        verbose_name_plural = _("Leads")

    def __str__(self):
        title = self.listing_title or self.subject or self.get_event_type_display()
        return f"{title} ({self.get_alert_status_display()})"


class NoiseAlert(MarketplaceAlert):
    class Meta:
        proxy = True
        verbose_name = _("Spam or newsletter email")
        verbose_name_plural = _("Spam and newsletters")


class ProcessedEmail(TimestampedModel):
    mailbox = models.ForeignKey(
        MailboxAccount,
        verbose_name=_("mailbox"),
        on_delete=models.CASCADE,
        related_name="processed_emails",
    )
    gmail_message_id = models.CharField("Gmail message ID", max_length=255)
    gmail_thread_id = models.CharField("Gmail thread ID", max_length=255, blank=True)
    subject = models.CharField(_("subject"), max_length=500, blank=True)
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    processed_at = models.DateTimeField(_("processed at"), default=timezone.now)

    class Meta:
        ordering = ["-processed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "gmail_message_id"],
                name="unique_processed_email_per_mailbox",
            ),
        ]
        verbose_name = _("Processed email")
        verbose_name_plural = _("Processed emails")

    def __str__(self):
        return f"{self.mailbox.email}: {self.gmail_message_id}"


class ServiceEvent(TimestampedModel):
    class EventType(models.TextChoices):
        MAILBOX_ERROR = "mailbox_error", _("Mailbox error")
        PARSER_ERROR = "parser_error", _("Parser error")
        TELEGRAM_SEND_ERROR = "telegram_send_error", _("Telegram send error")
        RECOVERY = "recovery", _("Recovery")

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        RECOVERED = "recovered", _("Recovered")
        IGNORED = "ignored", _("Ignored")

    mailbox = models.ForeignKey(
        MailboxAccount,
        verbose_name=_("mailbox"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_events",
    )
    alert = models.ForeignKey(
        MarketplaceAlert,
        verbose_name=_("lead"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_events",
    )
    event_type = models.CharField(_("event type"), max_length=32, choices=EventType.choices)
    severity = models.CharField(_("severity"), max_length=16, choices=Severity.choices)
    status = models.CharField(_("status"), max_length=16, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(_("source"), max_length=80, blank=True)
    title = models.CharField(_("title"), max_length=255)
    details = models.TextField(_("details"), blank=True)
    fingerprint = models.CharField("fingerprint", max_length=255, db_index=True)
    occurrences = models.PositiveIntegerField(_("occurrences"), default=1)
    first_seen_at = models.DateTimeField(_("first seen at"), default=timezone.now)
    last_seen_at = models.DateTimeField(_("last seen at"), default=timezone.now)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    telegram_sent_at = models.DateTimeField(_("sent to Telegram at"), null=True, blank=True)
    telegram_error = models.TextField(_("Telegram error"), blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]
        indexes = [
            models.Index(fields=["event_type", "status"]),
            models.Index(fields=["severity", "status"]),
            models.Index(fields=["fingerprint", "status"]),
        ]
        verbose_name = _("System log entry")
        verbose_name_plural = _("System log")

    def __str__(self):
        return f"{self.get_event_type_display()}: {self.title}"


class TelegramSettings(TimestampedModel):
    quiet_hours_enabled = models.BooleanField(_("quiet hours enabled"), default=False)
    quiet_hours_start = models.TimeField(_("quiet hours start"), default=time(22, 0))
    quiet_hours_end = models.TimeField(_("quiet hours end"), default=time(7, 0))
    allow_urgent_during_quiet_hours = models.BooleanField(
        _("send urgent alerts during quiet hours"),
        default=False,
    )

    class Meta:
        verbose_name = _("Telegram settings")
        verbose_name_plural = _("Telegram settings")

    def __str__(self):
        status = _("enabled") if self.quiet_hours_enabled else _("disabled")
        return _("Telegram settings: quiet hours %(status)s") % {"status": status}

    @classmethod
    def load(cls):
        settings = cls.objects.order_by("id").first()
        if settings:
            return settings
        return cls.objects.create()


class ArgusSettings(TimestampedModel):
    language_code = models.CharField(
        _("Interface language"),
        max_length=8,
        choices=LanguageCode.choices,
        default=LanguageCode.ENGLISH,
        help_text=_("Global language for Admin, mobile panel, and operational UI."),
    )

    class Meta:
        verbose_name = _("Argus settings")
        verbose_name_plural = _("Argus settings")

    def __str__(self):
        return f"Argus settings: {self.get_language_code_display()}"

    @classmethod
    def load(cls):
        settings = cls.objects.order_by("id").first()
        if settings:
            return settings
        return cls.objects.create()
