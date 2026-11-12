import logging
from datetime import timedelta
from io import BytesIO
from typing import Any

import resend
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from core import storage
from core.models import MediaAsset

logger = logging.getLogger(__name__)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def send_email(payload: dict[str, Any]) -> None:
    """Deliver one email through Resend. Payload is built by ResendCeleryEmailBackend."""
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(payload)


@shared_task
def read_image_dimensions(org_id: str, asset_id: str) -> None:
    """Store width/height for a ready image.

    If Pillow cannot open it (not really an image, or a decompression bomb), mark the asset
    invalid, delete its R2 object and log it. Invalid assets are never listed.
    """
    assets = MediaAsset.objects.for_org(org_id).filter(id=asset_id, status=MediaAsset.Status.READY)
    asset = assets.first()
    if asset is None:
        return
    try:
        with Image.open(BytesIO(storage.get_object_bytes(asset.file_key))) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        logger.warning(
            "Media asset %s (org %s) is not a readable %s; marked invalid and its object deleted",
            asset_id,
            org_id,
            asset.mime_type,
        )
        assets.update(status=MediaAsset.Status.INVALID, updated_at=timezone.now())
        storage.delete_object(asset.file_key)
        return
    assets.update(width=width, height=height)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def delete_media_object(org_id: str, asset_id: str) -> None:
    """Remove a deleted asset's R2 object, then its row."""
    asset = (
        MediaAsset.objects.for_org(org_id)
        .filter(id=asset_id, status=MediaAsset.Status.DELETING)
        .first()
    )
    if asset is None:
        return
    storage.delete_object(asset.file_key)
    asset.delete()


@shared_task
def purge_stale_uploads(max_age_hours: int = 24) -> int:
    """Daily (beat): delete pending uploads older than `max_age_hours`, objects first.

    A system maintenance task across all organizations, so it uses `unscoped` (rule 1 allows
    Celery tasks). Pending uploads were never visible, so no audit entry is written.
    """
    cutoff = timezone.now() - timedelta(hours=max_age_hours)
    stale = MediaAsset.unscoped.filter(status=MediaAsset.Status.PENDING, created_at__lt=cutoff)
    purged = 0
    for asset in stale.iterator():
        storage.delete_object(asset.file_key)
        asset.delete()
        purged += 1
    return purged
