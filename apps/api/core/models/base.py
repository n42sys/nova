from django.core.exceptions import ImproperlyConfigured
from django.db import models

from core.fields import uuid7


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantManager(models.Manager):
    """Refuses unscoped queries. App code must call `.for_org(org)`."""

    def get_queryset(self):
        raise ImproperlyConfigured("Use .for_org(org) or .unscoped")

    def for_org(self, org) -> models.QuerySet:
        if org is None:
            raise ImproperlyConfigured("for_org() requires an organization")
        return super().get_queryset().filter(organization=org)


class TenantModel(BaseModel):
    organization = models.ForeignKey("core.Organization", on_delete=models.PROTECT, db_index=True)

    # `unscoped` is declared first and is the default manager, so Django internals (related
    # managers, serialization, migrations) never hit the guard. App code uses `objects.for_org()`.
    unscoped = models.Manager()
    objects = TenantManager()

    class Meta:
        abstract = True
        default_manager_name = "unscoped"
