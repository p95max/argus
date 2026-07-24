from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0019_adminloginlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="adminloginlog",
            name="logged_out_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Logout time"),
        ),
        migrations.AddField(
            model_name="adminloginlog",
            name="path",
            field=models.CharField(default="", max_length=500, verbose_name="Path"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="adminloginlog",
            name="session_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64),
        ),
        migrations.AlterField(
            model_name="adminloginlog",
            name="logged_in_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                verbose_name="Attempt time",
            ),
        ),
        migrations.AlterModelOptions(
            name="adminloginlog",
            options={
                "ordering": ["-logged_in_at"],
                "verbose_name": "Access log",
                "verbose_name_plural": "Access logs",
            },
        ),
    ]
