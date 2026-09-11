from django.db import migrations


def backfill_active_status(apps, schema_editor):
    Listing = apps.get_model("alerts", "Listing")
    Listing.objects.filter(
        kleinanzeigen_status="unknown",
        kleinanzeigen_url__gt="",
        views_count__isnull=False,
    ).update(kleinanzeigen_status="active")


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0032_listing_kleinanzeigen_status"),
    ]

    operations = [
        migrations.RunPython(backfill_active_status, migrations.RunPython.noop),
    ]
