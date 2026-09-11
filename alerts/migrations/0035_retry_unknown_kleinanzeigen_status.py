from django.db import migrations


def retry_unknown_statuses(apps, schema_editor):
    Listing = apps.get_model("alerts", "Listing")
    Listing.objects.filter(
        kleinanzeigen_status="unknown",
    ).exclude(kleinanzeigen_url="").update(
        views_checked_at=None,
        views_error="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0034_recheck_kleinanzeigen_status"),
    ]

    operations = [
        migrations.RunPython(retry_unknown_statuses, migrations.RunPython.noop),
    ]
