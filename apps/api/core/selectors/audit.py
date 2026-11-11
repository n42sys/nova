import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from core.exceptions import ValidationFailed
from core.models import AuditLog, Organization

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    items: list[AuditLog]
    next_cursor: str | None


def _encode_cursor(entry: AuditLog) -> str:
    raw = f"{entry.created_at.isoformat()}|{entry.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, entry_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        parsed = datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            raise ValueError("naive datetime")
        return parsed, uuid.UUID(entry_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValidationFailed("Invalid cursor.", details={"cursor": cursor}) from exc


def list_audit_log(
    org: Organization, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> AuditLogPage:
    """Newest-first audit entries for `org`, cursor-paginated on (created_at, id)."""
    limit = max(1, min(limit, MAX_LIMIT))
    queryset = (
        AuditLog.objects.for_org(org).select_related("actor_user").order_by("-created_at", "-id")
    )
    if cursor:
        created_at, entry_id = _decode_cursor(cursor)
        queryset = queryset.filter(
            Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=entry_id)
        )

    items = list(queryset[: limit + 1])
    has_more = len(items) > limit
    items = items[:limit]
    return AuditLogPage(items=items, next_cursor=_encode_cursor(items[-1]) if has_more else None)
