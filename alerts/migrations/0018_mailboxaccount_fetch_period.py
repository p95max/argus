from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0017_alter_leadflag_options_alter_mailboxaccount_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mailboxaccount",
            name="fetch_period",
            field=models.CharField(
                choices=[
                    ("today", "Today"),
                    ("last_7_days", "Last 7 days"),
                    ("all", "No date limit"),
                ],
                default="today",
                help_text="Limits how far back Gmail messages are loaded.",
                max_length=20,
                verbose_name="Email fetch period",
            ),
        ),
    ]
