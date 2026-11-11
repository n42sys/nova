from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models.base import TenantModel

if TYPE_CHECKING:
    from core.models.site import Site


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    EVENT_STAFF = "event_staff", "Event staff"


SITE_ROLES = tuple(r for r in Role if r != Role.OWNER)  # ordered: used in a constraint


class Membership(TenantModel):
    """A user's place in an organization. `org_role` is null for site-only access."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    # Null (not "") means site-only access, per the design.
    org_role = models.CharField(  # noqa: DJ001
        max_length=20, choices=Role.choices, null=True, blank=True
    )

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="core_membership_org_user_unique"
            ),
            models.CheckConstraint(
                condition=Q(org_role__isnull=True) | Q(org_role__in=Role.values),
                name="core_membership_org_role_valid",
            ),
        ]

    def effective_role(self, site: Site) -> Role | None:
        """Owner -> SiteRole for `site` -> org_role -> None.

        Owners hold owner on every site; site roles never apply to them. Uses prefetched
        `site_roles` when present.
        """
        if self.org_role == Role.OWNER:
            return Role.OWNER
        for site_role in self.site_roles.all():
            if site_role.site_id == site.pk:
                return Role(site_role.role)
        return Role(self.org_role) if self.org_role else None


class SiteRole(TenantModel):
    """Overrides `Membership.org_role` on one site. Never `owner`."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="site_roles")
    site = models.ForeignKey("core.Site", on_delete=models.PROTECT, related_name="site_roles")
    role = models.CharField(
        max_length=20, choices=[(r.value, r.label) for r in Role if r in SITE_ROLES]
    )

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "site"], name="core_siterole_membership_site_unique"
            ),
            models.CheckConstraint(
                condition=Q(role__in=[r.value for r in SITE_ROLES]),
                name="core_siterole_role_not_owner",
            ),
        ]
