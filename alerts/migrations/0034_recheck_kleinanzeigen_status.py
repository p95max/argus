from django.db import migrations


def force_status_recheck(apps, schema_editor):
    Listing = apps.get_model("alerts", "Listing")
    Listing.objects.exclude(kleinanzeigen_url="").update(
        kleinanzeigen_status="unknown",
        views_checked_at=None,
        views_error="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0033_backfill_kleinanzeigen_status"),
    ]

    operations = [
        migrations.RunPython(force_status_recheck, migrations.RunPython.noop),
    ]
