from django.contrib import admin
from ..models import AdminLoginLog


@admin.register(AdminLoginLog)
class AdminLoginLogAdmin(admin.ModelAdmin):
    list_display = ("logged_in_at", "logged_out_at", "ip_address", "user", "user_agent", "path")
    list_filter = ("logged_in_at", "logged_out_at", "path", "user")
    search_fields = ("user__username", "user__email", "ip_address", "user_agent", "path")
    readonly_fields = (
        "user",
        "logged_in_at",
        "logged_out_at",
        "ip_address",
        "user_agent",
        "path",
    )
    date_hierarchy = "logged_in_at"

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
