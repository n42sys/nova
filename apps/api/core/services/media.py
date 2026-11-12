import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core import storage
from core.audit import audit
from core.context import RequestContext
from core.exceptions import NotFound, PermissionDenied, ValidationFailed
from core.fields import uuid7
from core.models import MediaAsset, Site
from core.pagination import DEFAULT_LIMIT, Page
from core.permissions import Perm, require
from core.selectors.media import list_media, media_scope
from core.services._changes import apply_changes
from core.tasks import delete_media_object, read_image_dimensions

ALLOWED_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/avif",
        "application/pdf",
        "audio/mpeg",
        "audio/mp4",
        "audio/aac",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "audio/flac",
        "video/mp4",
        "video/webm",
        "video/quicktime",
    }
)  # SVG is deliberately excluded: it can carry script.


@dataclass(frozen=True, slots=True)
class PendingUpload:
    asset: MediaAsset
    upload_url: str
    expires_at: datetime


def _safe_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")[:100]
    return name or "file"


def _metadata(asset: MediaAsset) -> dict:
    return {
        "file_key": asset.file_key,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "site_id": asset.site_id,
    }


def request_upload(
    ctx: RequestContext,
    *,
    filename: str,
    mime_type: str,
    size_bytes: int,
    site: Site | None = None,
) -> PendingUpload:
    """Create a pending asset under the caller's org prefix and presign a PUT for it."""
    require(ctx, Perm.MEDIA_UPLOAD, site)
    if site is not None and site.organization_id != ctx.organization.id:
        raise NotFound()
    mime_type = mime_type.strip().lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValidationFailed("This file type is not allowed.", details={"mime_type": [mime_type]})
    if not 0 < size_bytes <= settings.NOVA_MEDIA_MAX_BYTES:
        raise ValidationFailed(
            "File is too large.",
            details={"size_bytes": [size_bytes], "max_bytes": settings.NOVA_MEDIA_MAX_BYTES},
        )

    asset_id = uuid7()
    asset = MediaAsset(
        id=asset_id,
        organization=ctx.organization,
        site=site,
        file_key=f"orgs/{ctx.organization.id}/{asset_id}/{_safe_filename(filename)}",
        mime_type=mime_type,
        size_bytes=size_bytes,
        uploaded_by=ctx.user,
    )
    with transaction.atomic():
        asset.save(force_insert=True)
        audit(ctx, "media.upload_request", asset, _metadata(asset))
    return PendingUpload(
        asset=asset,
        upload_url=storage.presigned_put_url(asset.file_key, mime_type),
        expires_at=timezone.now() + timedelta(seconds=storage.PRESIGNED_PUT_EXPIRY),
    )


def confirm_upload(ctx: RequestContext, asset: MediaAsset, *, alt_text: str = "") -> MediaAsset:
    """Check the uploaded object and mark the asset ready.

    Missing object: 400, the asset stays pending (the client may retry). Wrong size or type:
    the object and the pending asset are deleted, then 400. Confirming twice is a no-op.
    """
    require(ctx, Perm.MEDIA_UPLOAD, asset.site)
    if asset.status == MediaAsset.Status.READY:
        return asset
    if asset.status != MediaAsset.Status.PENDING:
        raise NotFound()

    head = storage.head_object(asset.file_key)
    if head is None:
        raise ValidationFailed("The file has not been uploaded yet.")
    actual_size = head["ContentLength"]
    actual_type = (head.get("ContentType") or "").split(";")[0].strip().lower()
    if (
        actual_size != asset.size_bytes
        or actual_size > settings.NOVA_MEDIA_MAX_BYTES
        or actual_type != asset.mime_type
    ):
        storage.delete_object(asset.file_key)
        details = {
            "expected": {"size_bytes": asset.size_bytes, "mime_type": asset.mime_type},
            "received": {"size_bytes": actual_size, "mime_type": actual_type},
        }
        with transaction.atomic():
            audit(ctx, "media.upload_rejected", asset, {**_metadata(asset), **details})
            asset.delete()
        raise ValidationFailed(
            "The uploaded file does not match the upload request.", details=details
        )

    with transaction.atomic():
        asset.status = MediaAsset.Status.READY
        asset.alt_text = alt_text
        asset.save(update_fields=["status", "alt_text", "updated_at"])
        audit(ctx, "media.create", asset, _metadata(asset))
        if asset.mime_type.startswith("image/"):
            org_id, asset_id = asset.organization_id, asset.id
            transaction.on_commit(lambda: read_image_dimensions.delay(str(org_id), str(asset_id)))
    return asset


def update_media(ctx: RequestContext, asset: MediaAsset, *, alt_text: str) -> MediaAsset:
    require(ctx, Perm.MEDIA_UPLOAD, asset.site)
    with transaction.atomic():
        diff = apply_changes(asset, {"alt_text": alt_text})
        if diff:
            asset.save(update_fields=[*diff, "updated_at"])
            audit(ctx, "media.update", asset, {"changes": diff})
    return asset


def delete_media(ctx: RequestContext, asset: MediaAsset) -> None:
    """Hide the asset now; a task removes the R2 object and then the row."""
    require(ctx, Perm.MEDIA_DELETE, asset.site)
    with transaction.atomic():
        asset.status = MediaAsset.Status.DELETING
        asset.save(update_fields=["status", "updated_at"])
        audit(ctx, "media.delete", asset, _metadata(asset))
        org_id, asset_id = asset.organization_id, asset.id
        transaction.on_commit(lambda: delete_media_object.delay(str(org_id), str(asset_id)))


def view_media(
    ctx: RequestContext,
    *,
    site: Site | None = None,
    mime_prefix: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> Page:
    """Ready assets the caller may see: sites (and org-wide media) where they can upload."""
    site_ids, org_wide = media_scope(ctx.organization, ctx.membership)
    if not site_ids and not org_wide:
        raise PermissionDenied(details={"permission": Perm.MEDIA_UPLOAD.value})
    if site is not None and site.id not in site_ids:
        raise NotFound()
    return list_media(
        ctx.organization,
        site_ids=site_ids,
        include_org_wide=org_wide,
        site_id=site.id if site else None,
        mime_prefix=mime_prefix,
        cursor=cursor,
        limit=limit,
    )
