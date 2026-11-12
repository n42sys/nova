from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models.base import TenantModel
from core.models.membership import Role


class Invitation(TenantModel):
    """An invitation to join an organization. Only the SHA-256 hash of its token is stored."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        EXPIRED = "expired", "Expired"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"

    email = models.EmailField()
    org_role = models.CharField(  # noqa: DJ001  null = site roles only
        max_length=20, choices=Role.choices, null=True, blank=True
    )
    # [{"site_id": "<uuid>", "role": "editor" | "event_staff" | "admin"}]
    site_roles = models.JSONField(default=list, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="core_invitation_one_open_per_email",
            ),
            models.CheckConstraint(
                condition=Q(org_role__isnull=False) | ~Q(site_roles=[]),
                name="core_invitation_has_a_role",
            ),
            models.CheckConstraint(
                condition=Q(org_role__isnull=True) | Q(org_role__in=Role.values),
                name="core_invitation_org_role_valid",
            ),
        ]

    @property
    def status(self) -> "Invitation.Status":
        if self.accepted_at:
            return self.Status.ACCEPTED
        if self.revoked_at:
            return self.Status.REVOKED
        if self.expires_at <= timezone.now():
            return self.Status.EXPIRED
        return self.Status.OPEN
