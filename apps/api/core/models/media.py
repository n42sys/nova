from django.conf import settings
from django.db import models

from core.models.base import TenantModel


class MediaAsset(TenantModel):
    """Metadata for a file stored in R2. Org-wide when `site` is null.

    Lifecycle: pending (presigned PUT issued) -> ready (upload confirmed) -> deleting (object
    removal queued; the row is hard-deleted once the object is gone). An image that Pillow
    cannot open becomes invalid (object deleted, row kept as a record). Lists show only ready.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        DELETING = "deleting", "Deleting"
        INVALID = "invalid", "Invalid"

    site = models.ForeignKey(
        "core.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="media_assets"
    )
    file_key = models.CharField(max_length=512, unique=True)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    alt_text = models.CharField(max_length=500, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(
                fields=["organization", "status", "created_at", "id"],
                name="core_media_org_status_created",
            ),
        ]
