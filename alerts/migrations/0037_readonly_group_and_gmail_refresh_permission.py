from django.db import migrations


READONLY_PERMISSIONS = (
    ("admin", "logentry", "view_logentry", "Can view log entry"),
    ("alerts", "leadflag", "view_leadflag", "Can view Lead priority rule"),
    ("alerts", "mailboxaccount", "view_mailboxaccount", "Can view Mailbox"),
    ("alerts", "mailboxaccount", "refresh_mailboxaccount", "Can refresh Gmail mailbox"),
    ("alerts", "marketplacealert", "view_marketplacealert", "Can view Lead"),
    ("alerts", "noisealert", "view_noisealert", "Can view Spam or newsletter email"),
    ("alerts", "processedemail", "view_processedemail", "Can view Processed email"),
    ("alerts", "serviceevent", "view_serviceevent", "Can view System log entry"),
    ("alerts", "telegramsettings", "view_telegramsettings", "Can view Telegram settings"),
)


def create_readonly_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    group, _ = Group.objects.get_or_create(name="readonly")
    permissions = []

    for app_label, model, codename, name in READONLY_PERMISSIONS:
        content_type, _ = ContentType.objects.get_or_create(
            app_label=app_label,
            model=model,
        )
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions.append(permission)

    group.permissions.set(permissions)


def remove_readonly_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="readonly").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0036_recheck_active_kleinanzeigen_status"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="mailboxaccount",
            options={
                "ordering": ["email"],
                "permissions": [
                    ("refresh_mailboxaccount", "Can refresh Gmail mailbox"),
                ],
                "verbose_name": "Mailbox",
                "verbose_name_plural": "Mailboxes",
            },
        ),
        migrations.RunPython(create_readonly_group, remove_readonly_group),
    ]
