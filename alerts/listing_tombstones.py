from django.db import models


class DeletedListingIdentifier(models.Model):
    """Persistent tombstone preventing deleted Kleinanzeigen listings from reappearing."""

    kleinanzeigen_listing_id = models.CharField(max_length=80, unique=True, db_index=True)
    deleted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-deleted_at"]

    def __str__(self):
        return self.kleinanzeigen_listing_id
