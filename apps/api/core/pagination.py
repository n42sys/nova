"""Newest-first cursor pagination on (created_at, id), shared by list selectors."""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db.models import Model, Q, QuerySet

from core.exceptions import ValidationFailed

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class Page:
    items: list[Any]
    next_cursor: str | None


def _encode_cursor(item: Model) -> str:
    raw = f"{item.created_at.isoformat()}|{item.pk}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, item_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        parsed = datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            raise ValueError("naive datetime")
        return parsed, uuid.UUID(item_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValidationFailed("Invalid cursor.", details={"cursor": cursor}) from exc


def paginate(queryset: QuerySet, *, cursor: str | None, limit: int) -> Page:
    """One newest-first page of `queryset`; `limit` is clamped to 1..MAX_LIMIT."""
    limit = max(1, min(limit, MAX_LIMIT))
    queryset = queryset.order_by("-created_at", "-id")
    if cursor:
        created_at, item_id = _decode_cursor(cursor)
        queryset = queryset.filter(
            Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=item_id)
        )
    items = list(queryset[: limit + 1])
    has_more = len(items) > limit
    items = items[:limit]
    return Page(items=items, next_cursor=_encode_cursor(items[-1]) if has_more else None)
