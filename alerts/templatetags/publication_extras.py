from django import template

from ..services.listing_publication import listing_alert_info

register = template.Library()


@register.simple_tag
def publication_info(alert) -> dict:
    """Return listing state and identifier for alert detail actions."""
    try:
        return listing_alert_info(alert)
    except Exception:
        return {"state": "missing_id", "listing_id": "", "listing_url": ""}
