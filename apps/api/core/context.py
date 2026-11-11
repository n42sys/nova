from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Membership, Organization, User


class ActorType(StrEnum):
    USER = "user"
    TOKEN = "token"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Who is acting, in which organization. Built once per request and passed to services."""

    user: User | None
    membership: Membership | None
    organization: Organization
    ip: str | None
    actor_type: ActorType
