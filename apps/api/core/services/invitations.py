from datetime import timedelta
from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.audit import audit
from core.context import ActorType, RequestContext
from core.exceptions import Conflict, Gone, PermissionDenied, ValidationFailed
from core.models import SITE_ROLES, Invitation, Membership, Role, Site, SiteRole, User
from core.permissions import Perm, require
from core.selectors.invitations import list_invitations
from core.services.memberships import _set_site_role, require_can_grant
from core.tokens import new_invitation_token

INVITATION_TTL = timedelta(days=7)


def _normalise_site_roles(ctx: RequestContext, site_roles: list[dict[str, Any]]) -> list[dict]:
    """Validate [{"site_id", "role"}] against the org's active sites; return a JSON-safe copy."""
    site_ids = [str(item["site_id"]) for item in site_roles]
    if len(set(site_ids)) != len(site_ids):
        raise ValidationFailed("Each site may appear only once.", details={"site_roles": site_ids})
    for item in site_roles:
        if item["role"] not in SITE_ROLES:
            raise ValidationFailed(
                "Owner can only be granted as an organization role.",
                details={"site_roles": [item["role"]]},
            )
    known = {
        str(site_id)
        for site_id in Site.objects.for_org(ctx.organization)
        .filter(id__in=site_ids, status=Site.Status.ACTIVE)
        .values_list("id", flat=True)
    }
    if unknown := [site_id for site_id in site_ids if site_id not in known]:
        raise ValidationFailed("Unknown site.", details={"site_roles": unknown})
    return [{"site_id": str(item["site_id"]), "role": str(item["role"])} for item in site_roles]


def _send_invitation_email(invitation: Invitation, token: str) -> None:
    """Queue the email once the surrounding transaction commits."""
    link = f"{settings.NOVA_ADMIN_URL}/invite/{token}"
    org_name = invitation.organization.name
    inviter = (
        invitation.invited_by.name or invitation.invited_by.email if invitation.invited_by else None
    )
    lines = [
        f"You've been invited to join {org_name}" + (f" by {inviter}." if inviter else "."),
        "",
        f"Accept the invitation: {link}",
        "",
        f"This link expires on {invitation.expires_at:%Y-%m-%d %H:%M} UTC.",
    ]
    transaction.on_commit(
        lambda: send_mail(
            f"You've been invited to join {org_name}",
            "\n".join(lines),
            None,
            [invitation.email],
        )
    )


def _audit_metadata(invitation: Invitation) -> dict[str, Any]:
    return {
        "email": invitation.email,
        "org_role": invitation.org_role,
        "site_roles": invitation.site_roles,
    }


def invite_member(
    ctx: RequestContext,
    *,
    email: str,
    org_role: Role | None = None,
    site_roles: list[dict[str, Any]] | None = None,
) -> Invitation:
    """Invite `email` with an org role and/or site roles. Re-inviting revokes the open invite.

    Admins may invite only as editor or event_staff; owner and admin need an owner.
    """
    require(ctx, Perm.MEMBERS_MANAGE)
    site_roles = site_roles or []
    if org_role is None and not site_roles:
        raise ValidationFailed("Give an organization role, site roles, or both.")
    if org_role == Role.OWNER and site_roles:
        raise ValidationFailed("Owners cannot have site roles.", details={"site_roles": site_roles})
    require_can_grant(ctx, org_role, *(item["role"] for item in site_roles))
    site_roles = _normalise_site_roles(ctx, site_roles)
    email = email.strip().lower()

    token, token_hash = new_invitation_token()
    with transaction.atomic():
        now = timezone.now()
        previous = list(
            Invitation.objects.for_org(ctx.organization)
            .filter(email=email, accepted_at__isnull=True, revoked_at__isnull=True)
            .select_for_update()
        )
        for old in previous:
            old.revoked_at = now
            old.save(update_fields=["revoked_at", "updated_at"])
            audit(ctx, "invitation.revoke", old, {**_audit_metadata(old), "reason": "reinvited"})

        invitation = Invitation(
            organization=ctx.organization,
            email=email,
            org_role=org_role,
            site_roles=site_roles,
            token_hash=token_hash,
            invited_by=ctx.user,
            expires_at=now + INVITATION_TTL,
        )
        invitation.save(force_insert=True)
        audit(ctx, "invitation.create", invitation, _audit_metadata(invitation))
        _send_invitation_email(invitation, token)
    return invitation


def _require_can_manage(ctx: RequestContext, invitation: Invitation) -> None:
    require(ctx, Perm.MEMBERS_MANAGE)
    require_can_grant(ctx, invitation.org_role, *(item["role"] for item in invitation.site_roles))


def revoke_invitation(ctx: RequestContext, invitation: Invitation) -> Invitation:
    """Revoke an invitation that has not been accepted. Revoking twice is a no-op."""
    _require_can_manage(ctx, invitation)
    with transaction.atomic():
        invitation = (
            Invitation.objects.for_org(ctx.organization).select_for_update().get(id=invitation.id)
        )
        if invitation.accepted_at:
            raise Conflict("This invitation has already been accepted.")
        if invitation.revoked_at:
            return invitation
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at", "updated_at"])
        audit(ctx, "invitation.revoke", invitation, _audit_metadata(invitation))
    return invitation


def resend_invitation(ctx: RequestContext, invitation: Invitation) -> Invitation:
    """Email a fresh link. The old token stops working and the 7-day expiry restarts."""
    _require_can_manage(ctx, invitation)
    with transaction.atomic():
        invitation = (
            Invitation.objects.for_org(ctx.organization)
            .select_for_update(of=("self",))  # lock only the invitation, not the joined rows
            .select_related("organization", "invited_by")
            .get(id=invitation.id)
        )
        if invitation.accepted_at or invitation.revoked_at:
            raise Conflict(f"This invitation has been {invitation.status}.")
        token, invitation.token_hash = new_invitation_token()
        invitation.expires_at = timezone.now() + INVITATION_TTL
        invitation.save(update_fields=["token_hash", "expires_at", "updated_at"])
        audit(ctx, "invitation.resend", invitation, _audit_metadata(invitation))
        _send_invitation_email(invitation, token)
    return invitation


def view_invitations(ctx: RequestContext) -> list[Invitation]:
    """Invitations in the caller's organization; needs MEMBERS_VIEW."""
    require(ctx, Perm.MEMBERS_VIEW)
    return list_invitations(ctx.organization)


# Accepting

ROLE_RANK = {Role.EVENT_STAFF: 1, Role.EDITOR: 2, Role.ADMIN: 3, Role.OWNER: 4}


def _rank(role: str | None) -> int:
    return ROLE_RANK[Role(role)] if role else 0


def _mark_email_verified(user: User, email: str) -> None:
    address = EmailAddress.objects.filter(user=user, email__iexact=email).first()
    if address is None:
        has_primary = EmailAddress.objects.filter(user=user, primary=True).exists()
        EmailAddress.objects.create(user=user, email=email, verified=True, primary=not has_primary)
    elif not address.verified:
        address.verified = True
        address.save(update_fields=["verified"])


def accept_invitation(user: User, invitation: Invitation, *, ip: str | None) -> Membership:
    """Join the invitation's organization as `user`, in one transaction.

    Creates the membership, or merges into an existing one without ever lowering the
    member's effective role on any site: the org role becomes the higher of the two; an
    owner keeps no site roles; an invited site role is applied only where it is higher than
    the member's effective role there; site roles below a raised org role are dropped. Then
    marks the invitation accepted, marks the email verified and writes the audit entry.
    """
    org = invitation.organization
    with transaction.atomic():
        invitation = (
            Invitation.objects.for_org(org).select_for_update(of=("self",)).get(id=invitation.id)
        )
        if invitation.status != Invitation.Status.OPEN:
            raise Gone(
                f"This invitation has {invitation.status}.", details={"status": invitation.status}
            )
        if user.email.lower() != invitation.email:
            raise PermissionDenied("This invitation was sent to a different email address.")

        membership = Membership.objects.for_org(org).select_for_update().filter(user=user).first()
        created = membership is None
        previous_role = None if created else membership.org_role
        if created:
            membership = Membership(organization=org, user=user, org_role=invitation.org_role)
            membership.save(force_insert=True)
        elif _rank(invitation.org_role) > _rank(membership.org_role):
            membership.org_role = invitation.org_role
            membership.save(update_fields=["org_role", "updated_at"])

        site_roles = SiteRole.objects.for_org(org).filter(membership=membership)
        if membership.org_role == Role.OWNER:
            site_roles.delete()
        elif _rank(membership.org_role) > _rank(previous_role):
            site_roles.filter(
                role__in=[r for r in SITE_ROLES if _rank(r) < _rank(membership.org_role)]
            ).delete()

        applied = []
        if membership.org_role != Role.OWNER:
            sites = {
                str(site.id): site
                for site in Site.objects.for_org(org).filter(
                    id__in=[item["site_id"] for item in invitation.site_roles]
                )
            }
            for item in invitation.site_roles:
                site = sites.get(item["site_id"])
                if site is None:
                    continue
                membership = (
                    Membership.objects.for_org(org)
                    .prefetch_related("site_roles")
                    .get(id=membership.id)
                )
                if _rank(item["role"]) > _rank(membership.effective_role(site)):
                    _set_site_role(membership=membership, site=site, role=Role(item["role"]))
                    applied.append(item)

        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at", "updated_at"])
        _mark_email_verified(user, invitation.email)

        ctx = RequestContext(
            user=user, membership=membership, organization=org, ip=ip, actor_type=ActorType.USER
        )
        audit(
            ctx,
            "invitation.accept",
            invitation,
            {
                "membership_id": membership.id,
                "membership_created": created,
                "org_role": {"from": previous_role, "to": membership.org_role},
                "site_roles_applied": applied,
            },
        )
    return membership
