from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("alerts", "0023_reclassify_compact_buyer_messages")]

    operations = [
        migrations.CreateModel(
            name="Listing",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("title", models.CharField(max_length=255, verbose_name="listing title")),
                ("kleinanzeigen_url", models.URLField(blank=True, verbose_name="Kleinanzeigen URL")),
                ("kleinanzeigen_listing_id", models.CharField(blank=True, max_length=80, verbose_name="Kleinanzeigen listing ID")),
                ("views_count", models.PositiveIntegerField(blank=True, null=True, verbose_name="views")),
                ("views_checked_at", models.DateTimeField(blank=True, null=True, verbose_name="views checked at")),
                ("views_error", models.CharField(blank=True, max_length=120, verbose_name="views error")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("mailbox", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="listings", to="alerts.mailboxaccount", verbose_name="mailbox")),
            ],
            options={"verbose_name": "Listing", "verbose_name_plural": "Listings", "ordering": ["title", "id"]},
        ),
        migrations.AddIndex(model_name="listing", index=models.Index(fields=["is_active", "views_checked_at"], name="alerts_list_is_acti_3bd259_idx")),
        migrations.AddIndex(model_name="listing", index=models.Index(fields=["kleinanzeigen_listing_id"], name="alerts_list_kleinan_b7aa25_idx")),
        migrations.CreateModel(
            name="ListingViewStat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("views_count", models.PositiveIntegerField(verbose_name="views")),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="view_stats", to="alerts.listing", verbose_name="listing")),
            ],
            options={"verbose_name": "Listing view snapshot", "verbose_name_plural": "Listing view snapshots", "ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(model_name="listingviewstat", index=models.Index(fields=["listing", "created_at"], name="alerts_list_listin_565a37_idx")),
    ]
