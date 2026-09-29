import ipaddress
import logging

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import AdminLoginLog, Listing, ListingInquiryEvent, MarketplaceAlert
from .security import _client_ip
from .services.listing_publication import tombstone_listing_id

logger = logging.getLogger(__name__)


@receiver(user_logged_in, dispatch_uid="alerts.log_admin_login")
def log_admin_login(sender, request, user, **kwargs):
    if request.path != f"/{settings.DJANGO_ADMIN_URL}/login/" or not user.is_staff:
        return

    ip_address = _client_ip(request)
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        ip_address = None

    entry = AdminLoginLog.objects.create(
        user=user,
        ip_address=ip_address,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        path=request.path[:500],
        session_key=request.session.session_key or "",
    )
    request.session["admin_login_log_id"] = entry.pk


@receiver(user_logged_out, dispatch_uid="alerts.log_admin_logout")
def log_admin_logout(sender, request, user, **kwargs):
    entry_id = request.session.get("admin_login_log_id")
    if entry_id:
        AdminLoginLog.objects.filter(pk=entry_id, logged_out_at__isnull=True).update(
            logged_out_at=timezone.now()
        )


@receiver(post_delete, sender=Listing, dispatch_uid="alerts.remember_deleted_listing")
def remember_deleted_listing(sender, instance, **kwargs):
    if not instance.kleinanzeigen_listing_id:
        return
    try:
        tombstone_listing_id(instance.kleinanzeigen_listing_id)
    except Exception:
        logger.exception("Could not persist deleted listing ID %s", instance.kleinanzeigen_listing_id)


@receiver(post_save, sender=MarketplaceAlert, dispatch_uid="alerts.persist_listing_inquiry_event")
def persist_listing_inquiry_event(sender, instance, **kwargs):
    if instance.event_type != MarketplaceAlert.EventType.BUYER_MESSAGE:
        return

    listing = None
    if instance.listing_id:
        listing = (
            Listing.objects.filter(kleinanzeigen_listing_id=instance.listing_id)
            .only("id")
            .first()
        )

    occurred_at = instance.received_at or instance.created_at
    ListingInquiryEvent.objects.update_or_create(
        source_alert_id=instance.id,
        defaults={
            "listing": listing,
            "kleinanzeigen_listing_id": instance.listing_id or "",
            "listing_title": instance.listing_title or "",
            "occurred_at": occurred_at,
        },
    )
