from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0030_gmailpollingsettings_working_hours_enabled"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gmailpollingsettings",
            name="interval_minutes",
            field=models.PositiveSmallIntegerField(
                default=10,
                help_text="How often Gmail is checked while polling is allowed.",
                verbose_name="Gmail check interval (minutes)",
            ),
        ),
    ]
