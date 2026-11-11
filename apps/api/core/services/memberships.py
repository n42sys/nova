import uuid

from django.db import transaction

from core.audit import audit
from core.context import RequestContext
from core.exceptions import Conflict, NotFound, PermissionDenied, ValidationFailed
from core.models import SITE_ROLES, Membership, Role, Site, SiteRole
from core.permissions import Perm, require
from core.selectors.memberships import list_members


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


# Public member services. Every one requires MEMBERS_MANAGE (org-only) and refuses to act on
# the caller's own membership. Admins manage only roles below their own: they grant only
# editor or event_staff, and never touch a member whose org_role is admin or owner, nor any
# admin site role. Only owners grant, change or remove owner and admin. An organization
# always keeps at least one owner.

PRIVILEGED_ROLES = frozenset({Role.OWNER, Role.ADMIN})


def _refuse_self(ctx: RequestContext, membership: Membership) -> None:
    if membership.id == ctx.membership.id:
        raise PermissionDenied("You cannot change your own membership.")


def _refuse_beyond_admin_scope(ctx: RequestContext, target: Membership, *roles: str | None) -> None:
    """Owners may do anything here. Admins may act only on members below admin, and only
    with roles below admin: `roles` are the roles being granted, changed or removed."""
    if ctx.membership.org_role == Role.OWNER:
        return
    if target.org_role in PRIVILEGED_ROLES:
        raise PermissionDenied("Only owners can manage owners and admins.")
    if PRIVILEGED_ROLES.intersection(roles):
        raise PermissionDenied("Only owners can grant, change or remove the owner or admin role.")


def _lock_owner_ids(ctx: RequestContext) -> list[uuid.UUID]:
    """Lock the org's owner rows so concurrent demotions/removals serialize."""
    return list(
        Membership.objects.for_org(ctx.organization)
        .filter(org_role=Role.OWNER)
        .select_for_update()
        .values_list("id", flat=True)
    )


def _lock_member(ctx: RequestContext, membership: Membership) -> Membership:
    return Membership.objects.for_org(ctx.organization).select_for_update().get(id=membership.id)


def _site_role_summary(membership: Membership) -> list[dict[str, str]]:
    return [
        {"site_id": str(site_role.site_id), "role": site_role.role}
        for site_role in SiteRole.objects.for_org(membership.organization_id)
        .filter(membership=membership)
        .order_by("site_id")
    ]


def change_org_role(
    ctx: RequestContext, membership: Membership, org_role: Role | None
) -> Membership:
    """Set `membership.org_role`. Promoting to owner deletes the member's site roles."""
    require(ctx, Perm.MEMBERS_MANAGE)
    _refuse_self(ctx, membership)
    with transaction.atomic():
        owner_ids = _lock_owner_ids(ctx)
        target = _lock_member(ctx, membership)
        _refuse_beyond_admin_scope(ctx, target, org_role)
        if target.org_role == org_role:
            return target
        if target.id in owner_ids and len(owner_ids) == 1:
            raise Conflict("An organization must keep at least one owner.")

        metadata = {"user_id": target.user_id, "from": target.org_role, "to": org_role}
        if org_role == Role.OWNER:
            metadata["removed_site_roles"] = _site_role_summary(target)
            SiteRole.objects.for_org(ctx.organization).filter(membership=target).delete()
        target.org_role = org_role
        target.save(update_fields=["org_role", "updated_at"])
        audit(ctx, "member.role_change", target, metadata)
    return target


def remove_member(ctx: RequestContext, membership: Membership) -> None:
    """Remove a member from the organization, with their site roles."""
    require(ctx, Perm.MEMBERS_MANAGE)
    _refuse_self(ctx, membership)
    with transaction.atomic():
        owner_ids = _lock_owner_ids(ctx)
        target = _lock_member(ctx, membership)
        site_roles = SiteRole.objects.for_org(ctx.organization).filter(membership=target)
        _refuse_beyond_admin_scope(ctx, target, *site_roles.values_list("role", flat=True))
        if target.id in owner_ids and len(owner_ids) == 1:
            raise Conflict("An organization must keep at least one owner.")

        audit(
            ctx,
            "member.remove",
            target,
            {
                "user_id": target.user_id,
                "org_role": target.org_role,
                "site_roles": _site_role_summary(target),
            },
        )
        target.delete()


def set_site_role(ctx: RequestContext, membership: Membership, site: Site, role: Role) -> SiteRole:
    """Create or change a member's role on one site."""
    require(ctx, Perm.MEMBERS_MANAGE)
    _refuse_self(ctx, membership)
    with transaction.atomic():
        target = _lock_member(ctx, membership)
        previous = (
            SiteRole.objects.for_org(ctx.organization)
            .filter(membership=target, site=site)
            .values_list("role", flat=True)
            .first()
        )
        _refuse_beyond_admin_scope(ctx, target, role, previous)
        site_role = _set_site_role(membership=target, site=site, role=role)
        if previous != role:
            audit(
                ctx,
                "member.site_role_set",
                target,
                {"user_id": target.user_id, "site_id": site.id, "from": previous, "to": role},
            )
    return site_role


def remove_site_role(ctx: RequestContext, membership: Membership, site: Site) -> None:
    """Remove a member's role on one site; they fall back to their org role there."""
    require(ctx, Perm.MEMBERS_MANAGE)
    _refuse_self(ctx, membership)
    if site.organization_id != membership.organization_id:
        raise NotFound("Site not found.")
    with transaction.atomic():
        target = _lock_member(ctx, membership)
        site_role = (
            SiteRole.objects.for_org(ctx.organization).filter(membership=target, site=site).first()
        )
        _refuse_beyond_admin_scope(ctx, target, site_role.role if site_role else None)
        if site_role is None:
            return
        audit(
            ctx,
            "member.site_role_remove",
            target,
            {"user_id": target.user_id, "site_id": site.id, "role": site_role.role},
        )
        site_role.delete()


def view_members(ctx: RequestContext) -> list[Membership]:
    """Member list for the caller, who needs MEMBERS_VIEW."""
    require(ctx, Perm.MEMBERS_VIEW)
    return list_members(ctx.organization)
