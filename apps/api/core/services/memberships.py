from core.exceptions import NotFound, ValidationFailed
from core.models import SITE_ROLES, Membership, Role, Site, SiteRole


def _set_site_role(*, membership: Membership, site: Site, role: Role) -> SiteRole:
    """Internal: create or update `membership`'s role on `site`.

    Does no permission check and writes no audit entry. Do not call from views; the public
    services in T6 (member management) and T7 (invitation accept) wrap it with `require()`
    and `audit()`.
    """
    if site.organization_id != membership.organization_id:
        raise NotFound("Site not found.")
    if role not in SITE_ROLES:
        raise ValidationFailed(
            "Owner can only be granted as an organization role.", details={"role": role}
        )
    if membership.org_role == Role.OWNER:
        raise ValidationFailed("Owners cannot have site roles.", details={"role": role})

    site_role, _ = SiteRole.objects.for_org(membership.organization_id).update_or_create(
        organization_id=membership.organization_id,
        membership=membership,
        site=site,
        defaults={"role": role},
    )
    return site_role
