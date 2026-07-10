from django import forms
from django.utils.translation import gettext_lazy as _

from ..models import MailboxAccount


class MailboxFetchPeriodAdminForm(forms.ModelForm):
    fetch_period = forms.ChoiceField(
        label=_("Email fetch period"),
        choices=MailboxAccount.FetchPeriod.choices,
        widget=forms.RadioSelect,
        help_text=_(
            "Controls how far back Gmail is searched. Only superusers can change this setting."
        ),
    )

    class Meta:
        model = MailboxAccount
        fields = "__all__"


def configure_mailbox_fetch_period_admin(admin_class):
    admin_class.form = MailboxFetchPeriodAdminForm

    original_get_fieldsets = admin_class.get_fieldsets
    original_get_readonly_fields = getattr(admin_class, "get_readonly_fields", None)

    def get_fieldsets(self, request, obj=None):
        fieldsets = original_get_fieldsets(self, request, obj)
        if obj is None:
            fields = ["name", "is_active"]
            if request.user.is_superuser:
                fields.append("fetch_period")
            return (
                (
                    _("Main"),
                    {
                        "description": _(
                            "Create a mailbox, then connect Gmail through OAuth. "
                            "The email will be filled automatically after authorization."
                        ),
                        "fields": tuple(fields),
                    },
                ),
            )

        updated = []
        for title, options in fieldsets:
            options = dict(options)
            fields = list(options.get("fields", ()))
            if title == "Gmail" and "fetch_period" not in fields:
                fields.insert(1, "fetch_period")
            options["fields"] = tuple(fields)
            updated.append((title, options))
        return tuple(updated)

    def get_readonly_fields(self, request, obj=None):
        if original_get_readonly_fields is not None:
            readonly = list(original_get_readonly_fields(self, request, obj))
        else:
            readonly = list(self.readonly_fields)
        if not request.user.is_superuser and "fetch_period" not in readonly:
            readonly.append("fetch_period")
        return tuple(readonly)

    admin_class.get_fieldsets = get_fieldsets
    admin_class.get_readonly_fields = get_readonly_fields
