# Generated manually for Gmail OAuth in Admin.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0004_marketplacealert_telegram_chat_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mailboxaccount",
            name="gmail_connected_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="подключенный Gmail"),
        ),
        migrations.AddField(
            model_name="mailboxaccount",
            name="gmail_oauth_token",
            field=models.TextField(blank=True, verbose_name="Gmail OAuth token JSON"),
        ),
        migrations.AddField(
            model_name="mailboxaccount",
            name="gmail_oauth_connected_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Gmail подключен"),
        ),
        migrations.AddField(
            model_name="mailboxaccount",
            name="gmail_oauth_last_refresh_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="последнее обновление Gmail token"),
        ),
        migrations.AddField(
            model_name="mailboxaccount",
            name="gmail_oauth_error",
            field=models.TextField(blank=True, verbose_name="ошибка Gmail OAuth"),
        ),
    ]