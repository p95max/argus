from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from ..gmail.gmail import check_mailbox
from ..gmail.gmail_oauth import (
    build_gmail_authorization_url,
    complete_gmail_oauth_callback,
)
from ..models import MailboxAccount
from ..permissions import can_manage_mailboxes, can_view_mailbox_operations
from .ui import status_badge


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
                    "OAuth подключается из Admin. Токен хранится для конкретного "
                    "почтового ящика."
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
                "description": (
                    "Операционная диагностика: когда ящик проверялся и какая "
                    "ошибка была последней."
                ),
                "fields": (
                    "last_checked_at",
                    "last_success_at",
                    "last_error",
                    "created_at",
                    "updated_at",
                ),
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
        return status_badge(
            obj.get_connection_status_display(),
            css_by_status.get(obj.connection_status, "text-bg-secondary"),
        )

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
        disconnect_url = reverse(
            "admin:alerts_mailboxaccount_gmail_disconnect",
            args=[obj.pk],
        )
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
                f"fetched {result.fetched}, created {result.created}, "
                f"duplicates {result.duplicates}."
            ),
        )
        return redirect("admin:alerts_mailboxaccount_change", mailbox.id)

    @admin.action(description="Включить выбранные ящики")
    def enable_mailboxes(self, request, queryset):
        updated = queryset.update(
            is_active=True,
            connection_status=MailboxAccount.ConnectionStatus.NOT_CONNECTED,
        )
        self.message_user(request, f"Включено ящиков: {updated}.")

    @admin.action(description="Отключить выбранные ящики")
    def disable_mailboxes(self, request, queryset):
        updated = queryset.update(
            is_active=False,
            connection_status=MailboxAccount.ConnectionStatus.DISABLED,
        )
        self.message_user(request, f"Отключено ящиков: {updated}.")