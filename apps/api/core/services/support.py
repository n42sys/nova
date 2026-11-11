from typing import NoReturn

from core.context import RequestContext
from core.models import Organization


def start_support_session(ctx: RequestContext, organization: Organization) -> NoReturn:
    """Give an n42sys staff user (`is_staff`) audited, time-limited access to a tenant.

    `is_staff` is never a silent bypass: without a membership, staff get 404 like anyone else.
    Not implemented in Phase 1.
    """
    raise NotImplementedError("Support sessions are not implemented in Phase 1")
