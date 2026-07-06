from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0012_encrypt_gmail_oauth_tokens"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mailboxaccount",
            name="email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                null=True,
                unique=True,
                verbose_name="email",
            ),
        ),
    ]
