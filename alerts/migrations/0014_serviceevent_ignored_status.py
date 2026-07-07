from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0013_mailboxaccount_email_optional"),
    ]

    operations = [
        migrations.AlterField(
            model_name="serviceevent",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Открыто"),
                    ("recovered", "Восстановлено"),
                    ("ignored", "Игнор"),
                ],
                default="open",
                max_length=16,
                verbose_name="статус",
            ),
        ),
    ]
