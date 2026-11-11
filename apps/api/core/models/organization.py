from django.db import models

from core.models.base import BaseModel


class Organization(BaseModel):
    """The tenant. Not a TenantModel. Suspended, never deleted, in Phase 1."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=63, unique=True)
    features = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    def __str__(self) -> str:
        return self.name
