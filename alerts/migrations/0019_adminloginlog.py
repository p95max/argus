from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("alerts", "0018_mailboxaccount_fetch_period"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminLoginLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("logged_in_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="logged in at")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP address")),
                ("user_agent", models.CharField(blank=True, max_length=512, verbose_name="user agent")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="admin_login_logs", to=settings.AUTH_USER_MODEL, verbose_name="user")),
            ],
            options={
                "verbose_name": "Admin login",
                "verbose_name_plural": "Admin login log",
                "ordering": ["-logged_in_at"],
            },
        ),
    ]
