from django.db import migrations, models
import django.db.models.deletion


def backfill_listing_inquiry_events(apps, schema_editor):
    Listing = apps.get_model("alerts", "Listing")
    MarketplaceAlert = apps.get_model("alerts", "MarketplaceAlert")
    ListingInquiryEvent = apps.get_model("alerts", "ListingInquiryEvent")

    listings_by_external_id = {
        listing.kleinanzeigen_listing_id: listing
        for listing in Listing.objects.exclude(kleinanzeigen_listing_id="")
    }

    events = []
    alerts = MarketplaceAlert.objects.filter(event_type="buyer_message").order_by("id")
    for alert in alerts.iterator():
        events.append(
            ListingInquiryEvent(
                listing=listings_by_external_id.get(alert.listing_id),
                source_alert_id=alert.id,
                kleinanzeigen_listing_id=alert.listing_id or "",
                listing_title=alert.listing_title or "",
                occurred_at=alert.received_at or alert.created_at,
            )
        )

    ListingInquiryEvent.objects.bulk_create(events, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0038_rename_readonly_group_to_operator"),
    ]

    operations = [
        migrations.CreateModel(
            name="ListingInquiryEvent",
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
                (
                    "source_alert_id",
                    models.PositiveBigIntegerField(
                        db_index=True,
                        unique=True,
                        verbose_name="source alert ID",
                    ),
                ),
                (
                    "kleinanzeigen_listing_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=80,
                        verbose_name="Kleinanzeigen ad ID",
                    ),
                ),
                (
                    "listing_title",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="listing title",
                    ),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(db_index=True, verbose_name="occurred at"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="created at"),
                ),
                (
                    "listing",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inquiry_events",
                        to="alerts.listing",
                        verbose_name="listing",
                    ),
                ),
            ],
            options={
                "verbose_name": "Listing inquiry event",
                "verbose_name_plural": "Listing inquiry events",
                "ordering": ["-occurred_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="listinginquiryevent",
            index=models.Index(
                fields=["kleinanzeigen_listing_id", "occurred_at"],
                name="alerts_inq_listing_time_idx",
            ),
        ),
        migrations.RunPython(
            backfill_listing_inquiry_events,
            migrations.RunPython.noop,
        ),
    ]
