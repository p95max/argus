from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


TOGGLE_PERMISSION = (
    "alerts",
    "gmailpollingsettings",
    "toggle_gmail_polling",
    "Can pause or resume automatic Gmail polling",
)


def create_toggle_permission_and_assign_operator(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    app_label, model, codename, name = TOGGLE_PERMISSION
    content_type, _ = ContentType.objects.get_or_create(
        app_label=app_label,
        model=model,
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=codename,
        defaults={"name": name},
    )

    operator = Group.objects.filter(name="operator").first()
    if operator is not None:
        operator.permissions.add(permission)


def remove_toggle_permission_from_operator(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    operator = Group.objects.filter(name="operator").first()
    if operator is None:
        return

    permission = Permission.objects.filter(
        content_type__app_label="alerts",
        content_type__model="gmailpollingsettings",
        codename="toggle_gmail_polling",
    ).first()
    if permission is not None:
        operator.permissions.remove(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0039_listing_inquiry_event"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="gmailpollingsettings",
            name="polling_enabled",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Disable to pause scheduled Gmail API checks. "
                    "Manual checks remain available."
                ),
                verbose_name="automatic Gmail polling enabled",
            ),
        ),
        migrations.AddField(
            model_name="gmailpollingsettings",
            name="paused_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="paused at",
            ),
        ),
        migrations.AddField(
            model_name="gmailpollingsettings",
            name="paused_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="paused by",
            ),
        ),
        migrations.AlterModelOptions(
            name="gmailpollingsettings",
            options={
                "permissions": [
                    (
                        "toggle_gmail_polling",
                        "Can pause or resume automatic Gmail polling",
                    )
                ],
                "verbose_name": "Gmail polling settings",
                "verbose_name_plural": "Gmail polling settings",
            },
        ),
        migrations.RunPython(
            create_toggle_permission_and_assign_operator,
            remove_toggle_permission_from_operator,
        ),
    ]
