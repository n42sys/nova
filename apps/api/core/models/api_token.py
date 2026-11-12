from django.db import models

from core.models.base import TenantModel


class ApiToken(TenantModel):
    """A bearer token for one site. Only the SHA-256 of its secret is stored."""

    class Kind(models.TextChoices):
        DELIVERY = "delivery", "Delivery"
        PREVIEW = "preview", "Preview"

    site = models.ForeignKey("core.Site", on_delete=models.PROTECT, related_name="api_tokens")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    prefix = models.CharField(max_length=8, unique=True)  # in clear, for lookup
    token_hash = models.CharField(max_length=64)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
