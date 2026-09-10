from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0027_normalize_kleinanzeigen_listing_ids"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeletedListingIdentifier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kleinanzeigen_listing_id", models.CharField(db_index=True, max_length=80, unique=True)),
                ("deleted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-deleted_at"]},
        ),
    ]
