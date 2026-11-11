from django.db import models
from django.db.models.functions import Lower

from core.fields import LowercaseCharField
from core.models.base import TenantModel


class Site(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=63)
    domain = LowercaseCharField(max_length=253, null=True, blank=True, unique=True)
    timezone = models.CharField(max_length=64, default="Africa/Nairobi")
    default_locale = models.CharField(max_length=16, default="en")
    settings = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="core_site_org_slug_unique"
            ),
            # Domains are stored lowercase by the field; this also covers raw SQL writes.
            models.UniqueConstraint(Lower("domain"), name="core_site_domain_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.name
