import re

from django.db import migrations, models


def _ad_id(value):
    """Return the stable numeric part from historical Kleinanzeigen ID forms."""

    match = re.fullmatch(r"\s*(\d{5,})(?:-\d+)*\s*", value or "")
    if match:
        return match.group(1)
    match = re.search(r"/s-anzeige/(?:[^/?#]+/)*(\d{5,})(?:-\d+)*/?", value or "")
    return match.group(1) if match else ""


def normalize_listing_ids_and_merge_duplicates(apps, schema_editor):
    Listing = apps.get_model("alerts", "Listing")
    ListingViewStat = apps.get_model("alerts", "ListingViewStat")
    MarketplaceAlert = apps.get_model("alerts", "MarketplaceAlert")

    # MarketplaceAlert rows are messages, so several rows per ad are expected.
    # Only normalize IDs whose historical representation is unambiguously numeric.
    for alert in MarketplaceAlert.objects.exclude(listing_id="").iterator():
        ad_id = _ad_id(alert.listing_id)
        if ad_id and ad_id != alert.listing_id:
            MarketplaceAlert.objects.filter(pk=alert.pk).update(listing_id=ad_id)

    groups = {}
    for listing in Listing.objects.order_by("id").iterator():
        ad_id = _ad_id(listing.kleinanzeigen_listing_id) or _ad_id(listing.kleinanzeigen_url)
        if not ad_id:
            # This field is exclusively for a stable Kleinanzeigen ID.  Keep
            # the URL/title for audit, but remove obsolete non-canonical data
            # before the unique constraint is installed.
            if listing.kleinanzeigen_listing_id:
                Listing.objects.filter(pk=listing.pk).update(kleinanzeigen_listing_id="")
            continue
        groups.setdefault(ad_id, []).append(listing)

    for ad_id, rows in groups.items():
        canonical = rows[0]
        latest = max(rows, key=lambda row: (row.views_checked_at or row.updated_at, row.pk))
        duplicate_ids = [row.pk for row in rows[1:]]

        if duplicate_ids:
            # Snapshots are observations, not values to sum.  Their original
            # timestamps remain intact when moved to the canonical tracker.
            ListingViewStat.objects.filter(listing_id__in=duplicate_ids).update(listing_id=canonical.pk)

        canonical.kleinanzeigen_listing_id = ad_id
        canonical.title = canonical.title or latest.title
        canonical.kleinanzeigen_url = canonical.kleinanzeigen_url or latest.kleinanzeigen_url
        canonical.mailbox_id = canonical.mailbox_id or latest.mailbox_id
        canonical.source_alert_id = canonical.source_alert_id or latest.source_alert_id
        canonical.is_active = any(row.is_active for row in rows)
        if latest.views_count is not None:
            canonical.views_count = latest.views_count
            canonical.views_checked_at = latest.views_checked_at
            canonical.views_error = latest.views_error
        canonical.save()

        if duplicate_ids:
            Listing.objects.filter(pk__in=duplicate_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0026_listing_source_alert"),
    ]

    operations = [
        migrations.RunPython(normalize_listing_ids_and_merge_duplicates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="listing",
            name="kleinanzeigen_listing_id",
            field=models.CharField(blank=True, max_length=80, verbose_name="Kleinanzeigen ad ID"),
        ),
        migrations.AddConstraint(
            model_name="listing",
            constraint=models.UniqueConstraint(
                condition=~models.Q(kleinanzeigen_listing_id=""),
                fields=("kleinanzeigen_listing_id",),
                name="unique_kleinanzeigen_ad_id",
            ),
        ),
    ]
