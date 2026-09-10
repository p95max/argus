# Generated manually for Gmail polling schedule settings.

import datetime

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0028_deletedlistingidentifier"),
    ]

    operations = [
        migrations.CreateModel(
            name="GmailPollingSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                (
                    "interval_minutes",
                    models.PositiveSmallIntegerField(
                        default=10,
                        help_text="How often Gmail is checked during working hours.",
                        verbose_name="Gmail check interval (minutes)",
                    ),
                ),
                (
                    "working_hours_start",
                    models.TimeField(
                        default=datetime.time(7, 0),
                        verbose_name="working hours start",
                    ),
                ),
                (
                    "working_hours_end",
                    models.TimeField(
                        default=datetime.time(23, 0),
                        verbose_name="working hours end",
                    ),
                ),
            ],
            options={
                "verbose_name": "Gmail polling settings",
                "verbose_name_plural": "Gmail polling settings",
            },
        ),
    ]
