import uuid

from django.db.models import Q

from core.models import MediaAsset, Membership, Organization, Site
from core.pagination import DEFAULT_LIMIT, Page, paginate
from core.permissions import Perm, member_has_perm


def media_scope(org: Organization, membership: Membership) -> tuple[set[uuid.UUID], bool]:
    """(site ids, org-wide?) whose media the member may see: where they hold MEDIA_UPLOAD."""
    site_ids = {
        site.id
        for site in Site.objects.for_org(org)
        if member_has_perm(membership, Perm.MEDIA_UPLOAD, site)
    }
    return site_ids, member_has_perm(membership, Perm.MEDIA_UPLOAD)


def list_media(
    org: Organization,
    *,
    site_ids: set[uuid.UUID],
    include_org_wide: bool,
    site_id: uuid.UUID | None = None,
    mime_prefix: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> Page:
    """Newest-first READY assets within the given scope."""
    scope = Q(site_id__in=site_ids)
    if include_org_wide:
        scope |= Q(site__isnull=True)
    queryset = (
        MediaAsset.objects.for_org(org)
        .filter(scope, status=MediaAsset.Status.READY)
        .select_related("uploaded_by")
    )
    if site_id is not None:
        queryset = queryset.filter(site_id=site_id)
    if mime_prefix:
        queryset = queryset.filter(mime_type__startswith=mime_prefix.lower())
    return paginate(queryset, cursor=cursor, limit=limit)


def get_media(
    org: Organization,
    asset_id: uuid.UUID,
    *,
    statuses: tuple[str, ...] = (MediaAsset.Status.READY,),
) -> MediaAsset | None:
    return (
        MediaAsset.objects.for_org(org)
        .filter(id=asset_id, status__in=statuses)
        .select_related("site", "uploaded_by")
        .first()
    )
