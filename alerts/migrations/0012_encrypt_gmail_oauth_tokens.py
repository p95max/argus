from django.db import migrations


def encrypt_existing_tokens(apps, schema_editor):
    from alerts.crypto import encrypt_text, is_encrypted

    MailboxAccount = apps.get_model("alerts", "MailboxAccount")
    for mailbox in MailboxAccount.objects.exclude(gmail_oauth_token="").iterator():
        token = mailbox.gmail_oauth_token
        if is_encrypted(token):
            continue
        mailbox.gmail_oauth_token = encrypt_text(token)
        mailbox.save(update_fields=["gmail_oauth_token"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0011_marketplacealert_taken_at_marketplacealert_taken_by_and_more"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_tokens, noop_reverse),
    ]
