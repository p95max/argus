from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0025_merge_0024_branches"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="source_alert",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="view_statistics",
                to="alerts.marketplacealert",
                verbose_name="source listing alert",
            ),
        ),
    ]
