from django import template

from ..services.listing_publication import publication_listing_candidate

register = template.Library()


@register.simple_tag
def publication_add_available(alert) -> bool:
    """Return whether a publication alert can create a new tracked listing."""
    try:
        return publication_listing_candidate(alert) is not None
    except Exception:
        return False
