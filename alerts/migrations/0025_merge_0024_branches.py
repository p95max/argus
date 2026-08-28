from django.db import migrations


class Migration(migrations.Migration):
    """Join the independently added listing statistics and reply reparsing migrations."""

    dependencies = [
        ("alerts", "0024_direct_reply_scam_support"),
        ("alerts", "0024_listing_view_statistics"),
    ]

    operations = []
