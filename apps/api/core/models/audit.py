from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from core.models.base import TenantManager, TenantModel


class AppendOnlyError(Exception):
    """Raised on any attempt to change or delete an audit log entry."""


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("AuditLog is append-only")

    def delete(self):
        raise AppendOnlyError("AuditLog is append-only")


class AuditLog(TenantModel):
    """Append-only record of every data change. Written only through `core.audit.audit()`."""

    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    # ApiToken arrives in T8; stored as a plain id so history survives token changes.
    actor_token_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True, blank=True)
    updated_at = None  # rows never change

    unscoped = AuditLogQuerySet.as_manager()
    objects = TenantManager.from_queryset(AuditLogQuerySet)()

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(
                fields=["organization", "created_at", "id"], name="core_auditlog_org_created"
            ),
        ]

    def save(self, *args, **kwargs):
        # Integrity guard, not business logic: existing rows can never be rewritten.
        if not self._state.adding:
            raise AppendOnlyError("AuditLog is append-only")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("AuditLog is append-only")
