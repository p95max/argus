import re
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from django.db import migrations, models


PUBLICATION_RE = re.compile(
    r"(?:anzeige wurde erfolgreich ver(?:ö|oe)ffentlicht|erfolgreich ver(?:ö|oe)ffentlicht)",
    flags=re.IGNORECASE,
)
URL_RE = re.compile(
    r"https://(?:www\.)?kleinanzeigen\.de/s-anzeige/[^\s\"'<>]+",
    flags=re.IGNORECASE,
)
PATH_RE = re.compile(r"/s-anzeige/(?:[^/?#]+/)*(?P<listing_id>\d+(?:-\d+)*)/?")


def backfill_published_listings(apps, schema_editor):
    Listing = apps.get_model("alerts", "Listing")
    MarketplaceAlert = apps.get_model("alerts", "MarketplaceAlert")

    alerts = MarketplaceAlert.objects.filter(event_type="system_notice").order_by("created_at", "id")
    for alert in alerts.iterator():
        text = unescape(f"{alert.raw_subject}\n{alert.raw_body}\n{alert.normalized_body}")
        if not PUBLICATION_RE.search(text):
            continue

        listing_url = ""
        ad_id = ""
        for candidate in URL_RE.findall(text):
            candidate = candidate.rstrip(".,);]")
            parts = urlsplit(candidate)
            match = PATH_RE.fullmatch(parts.path)
            if parts.scheme != "https" or parts.hostname not in {"kleinanzeigen.de", "www.kleinanzeigen.de"} or not match:
                continue
            listing_id = match.group("listing_id")
            ad_id = listing_id.split("-", 1)[0]
            listing_url = urlunsplit(("https", "www.kleinanzeigen.de", parts.path.rstrip("/"), "", ""))
            break

        if not ad_id or Listing.objects.filter(kleinanzeigen_listing_id=ad_id).exists():
            continue

        title = (alert.listing_title or alert.subject or f"Kleinanzeigen {ad_id}").strip()[:255]
        Listing.objects.create(
            title=title,
            source_alert_id=alert.id,
            mailbox_id=alert.mailbox_id,
            kleinanzeigen_url=listing_url,
            kleinanzeigen_listing_id=ad_id,
            is_active=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0027_normalize_kleinanzeigen_listing_ids"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeletedListingIdentifier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kleinanzeigen_listing_id", models.CharField(db_index=True, max_length=80, unique=True)),
                ("deleted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-deleted_at"]},
        ),
        migrations.RunPython(backfill_published_listings, migrations.RunPython.noop),
    ]
