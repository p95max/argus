from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0029_gmailpollingsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="gmailpollingsettings",
            name="working_hours_enabled",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When enabled, Gmail is not checked outside the configured working hours. "
                    "Disable this option to check Gmail around the clock."
                ),
                verbose_name="restrict Gmail checks to working hours",
            ),
        ),
    ]
