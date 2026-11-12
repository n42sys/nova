import uuid
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from core.models import Invitation, Organization, Site, User


def _open(queryset: QuerySet[Invitation]) -> QuerySet[Invitation]:
    return queryset.filter(
        accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
    )


def list_invitations(org: Organization) -> list[Invitation]:
    return list(
        Invitation.objects.for_org(org).select_related("invited_by").order_by("-created_at", "-id")
    )


def get_invitation(org: Organization, invitation_id: uuid.UUID) -> Invitation | None:
    return Invitation.objects.for_org(org).filter(id=invitation_id).first()


def get_open_invitation(org_id: uuid.UUID, invitation_id: uuid.UUID) -> Invitation | None:
    """Open (not accepted, revoked or expired) invitation in an active organization."""
    return (
        _open(Invitation.objects.for_org(org_id))
        .filter(id=invitation_id, organization__status=Organization.Status.ACTIVE)
        .first()
    )


def invitation_sites(invitation: Invitation) -> dict[str, Site]:
    """The invitation's sites in its organization, keyed by id string."""
    site_ids = [item["site_id"] for item in invitation.site_roles]
    sites = Site.objects.for_org(invitation.organization_id).filter(id__in=site_ids)
    return {str(site.id): site for site in sites}


def invitee_has_account(invitation: Invitation) -> bool:
    return User.objects.filter(email__iexact=invitation.email).exists()


def invitation_preview(invitation: Invitation) -> dict[str, Any]:
    """What the public invitation page shows: org, inviter, roles with site names."""
    sites = invitation_sites(invitation)
    inviter = invitation.invited_by
    return {
        "organization": invitation.organization,
        "email": invitation.email,
        "invited_by_name": (inviter.name or inviter.email) if inviter else None,
        "org_role": invitation.org_role,
        "site_roles": [
            {
                "site_id": item["site_id"],
                "site_name": sites[item["site_id"]].name,
                "role": item["role"],
            }
            for item in invitation.site_roles
            if item["site_id"] in sites
        ],
        "expires_at": invitation.expires_at,
        "account_exists": invitee_has_account(invitation),
    }
