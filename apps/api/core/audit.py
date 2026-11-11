from typing import Any

from django.db import models

from core.context import ActorType, RequestContext
from core.models import AuditLog

SENSITIVE_KEY_PARTS = ("secret", "token", "password")


def _is_sensitive(key: str) -> bool:
    key = key.lower()
    return any(part in key for part in SENSITIVE_KEY_PARTS)


def _scrub(value: Any) -> Any:
    """Drop keys that look like secrets, at any depth."""
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items() if not _is_sensitive(str(key))}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def audit(
    ctx: RequestContext,
    action: str,
    target: models.Model | None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry for `action` on `target` in `ctx.organization`.

    Keys containing "secret", "token" or "password" (case-insensitive, at any depth) are
    removed from `metadata` before it is written.
    """
    entry = AuditLog(
        organization=ctx.organization,
        actor_user=ctx.user if ctx.actor_type == ActorType.USER else None,
        action=action,
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        metadata=_scrub(metadata or {}),
        ip=ctx.ip,
    )
    entry.save()
    return entry
