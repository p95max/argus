from django.db import migrations


def rename_readonly_group_to_operator(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")

    readonly = Group.objects.filter(name="readonly").first()
    if readonly is None:
        return

    operator = Group.objects.filter(name="operator").first()
    if operator is None:
        readonly.name = "operator"
        readonly.save(update_fields=["name"])
        return

    operator.permissions.add(*readonly.permissions.all())
    for user in User.objects.filter(groups=readonly).iterator():
        user.groups.add(operator)
    readonly.delete()


def rename_operator_group_to_readonly(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")

    operator = Group.objects.filter(name="operator").first()
    if operator is None:
        return

    readonly = Group.objects.filter(name="readonly").first()
    if readonly is None:
        operator.name = "readonly"
        operator.save(update_fields=["name"])
        return

    readonly.permissions.add(*operator.permissions.all())
    for user in User.objects.filter(groups=operator).iterator():
        user.groups.add(readonly)
    operator.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0037_readonly_group_and_gmail_refresh_permission"),
    ]

    operations = [
        migrations.RunPython(
            rename_readonly_group_to_operator,
            rename_operator_group_to_readonly,
        ),
    ]
