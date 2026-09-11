from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0031_alter_gmailpollingsettings_interval_minutes"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="kleinanzeigen_status",
            field=models.CharField(
                choices=[
                    ("unknown", "Unknown"),
                    ("active", "Active"),
                    ("reserved", "Reserved"),
                    ("deleted", "Deleted"),
                ],
                default="unknown",
                max_length=16,
                verbose_name="Kleinanzeigen status",
            ),
        ),
    ]
