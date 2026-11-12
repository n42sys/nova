"""Resolve secret tokens to the tenant object they belong to.

This is the ONE module in request-handling code allowed to use `Model.unscoped` (rule 1 in
CLAUDE.md). A token arrives without an organization, so lookup must cross tenants; the
token's hash (or, from T8, an API token's prefix) is the only filter, and every function
returns the object with its organization loaded so callers continue with `for_org()`.
Keep this module small and review every change to it.
"""

from core.models import Invitation, Organization
from core.tokens import hash_token, is_well_formed_invitation_token


def resolve_invitation_token(token: str) -> Invitation | None:
    """Invitation for a raw token, in any state, if its organization is active."""
    if not is_well_formed_invitation_token(token):
        return None
    return (
        Invitation.unscoped.filter(
            token_hash=hash_token(token), organization__status=Organization.Status.ACTIVE
        )
        .select_related("organization", "invited_by")
        .first()
    )
