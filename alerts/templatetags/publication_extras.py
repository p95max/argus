from django import template

from ..services.listing_publication import publication_listing_state

register = template.Library()


@register.simple_tag
def publication_state(alert) -> str:
    """Return the publication listing state for the alert detail UI."""
    try:
        return publication_listing_state(alert)
    except Exception:
        return "missing_id"
