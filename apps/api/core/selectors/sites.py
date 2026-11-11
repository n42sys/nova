import uuid

from core.models import Membership, Organization, Site
from core.permissions import Perm, member_has_perm


def get_visible_site(
    org: Organization, site_id: uuid.UUID, *, membership: Membership
) -> Site | None:
    """A site in `org` the member may view (archived included), or None."""
    site = Site.objects.for_org(org).filter(id=site_id).first()
    if site is None or not member_has_perm(membership, Perm.SITE_VIEW, site):
        return None
    return site


def list_sites(org: Organization, *, membership: Membership) -> list[Site]:
    """Active sites in `org` where the member has SITE_VIEW, by name."""
    sites = Site.objects.for_org(org).filter(status=Site.Status.ACTIVE).order_by("name", "id")
    return [site for site in sites if member_has_perm(membership, Perm.SITE_VIEW, site)]


def get_site(org: Organization, site_id: uuid.UUID) -> Site | None:
    """Any site in `org`, archived included, with no visibility filter (for org-level admin)."""
    return Site.objects.for_org(org).filter(id=site_id).first()
