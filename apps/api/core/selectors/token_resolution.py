"""Resolve secret tokens to the tenant object they belong to.

This is the ONE module in request-handling code allowed to use `Model.unscoped` (rule 1 in
CLAUDE.md). A token arrives without an organization, so lookup must cross tenants; the
token's hash (or, from T8, an API token's prefix) is the only filter, and every function
returns the object with its organization loaded so callers continue with `for_org()`.
Keep this module small and review every change to it.
"""

import hmac

from core.models import ApiToken, Invitation, Organization, Site
from core.tokens import hash_token, is_well_formed_invitation_token, parse_api_token


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


def resolve_api_token(raw: str) -> ApiToken | None:
    """Active ApiToken for a raw bearer token, with its organization and site loaded.

    None if the token is malformed, unknown, of the wrong kind for its prefix, revoked, or
    if its site is archived or its organization suspended. The secret is compared in
    constant time against the stored hash.
    """
    parsed = parse_api_token(raw)
    if parsed is None:
        return None
    token = (
        ApiToken.unscoped.filter(prefix=parsed.prefix)
        .select_related("organization", "site")
        .first()
    )
    if token is None or not hmac.compare_digest(hash_token(parsed.secret), token.token_hash):
        return None
    if (
        token.kind != parsed.kind
        or token.revoked_at is not None
        or token.organization.status != Organization.Status.ACTIVE
        or token.site.status != Site.Status.ACTIVE
    ):
        return None
    return token
