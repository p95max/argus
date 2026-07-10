from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from ..attention import filter_needs_attention, needs_attention_alert_q


def status_badge(text, css_class):
    return format_html('<span class="badge {}">{}</span>', css_class, text)


class NeedsAttentionFilter(admin.SimpleListFilter):
    title = _("Needs attention")
    parameter_name = "needs_attention"

    def lookups(self, request, model_admin):
        return (
            ("yes", _("Yes")),
            ("no", _("No")),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return filter_needs_attention(queryset)

        if self.value() == "no":
            return queryset.exclude(needs_attention_alert_q()).distinct()

        return queryset
