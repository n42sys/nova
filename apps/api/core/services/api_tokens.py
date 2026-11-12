from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.audit import audit
from core.context import RequestContext
from core.exceptions import NotFound
from core.models import ApiToken, Site
from core.permissions import Perm, require
from core.selectors.api_tokens import list_api_tokens
from core.tokens import new_api_token

_PREFIX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class CreatedApiToken:
    token: ApiToken
    raw: str  # shown once in the create response, never stored


def create_api_token(
    ctx: RequestContext, site: Site, *, name: str, kind: ApiToken.Kind
) -> CreatedApiToken:
    require(ctx, Perm.API_TOKENS_MANAGE, site)
    if site.organization_id != ctx.organization.id:
        raise NotFound()
    for attempt in range(_PREFIX_ATTEMPTS):
        raw, prefix, token_hash = new_api_token(kind)
        try:
            with transaction.atomic():
                token = ApiToken(
                    organization=ctx.organization,
                    site=site,
                    name=name,
                    kind=kind,
                    prefix=prefix,
                    token_hash=token_hash,
                )
                token.save(force_insert=True)
                audit(
                    ctx,
                    "api_token.create",
                    token,
                    {"name": name, "kind": kind, "prefix": prefix, "site_id": site.id},
                )
            return CreatedApiToken(token=token, raw=raw)
        except IntegrityError:  # prefix collision (1 in ~2.8e12); try a new one
            if attempt == _PREFIX_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def revoke_api_token(ctx: RequestContext, token: ApiToken) -> ApiToken:
    """Revoke immediately. Revoking twice is a no-op."""
    require(ctx, Perm.API_TOKENS_MANAGE, token.site)
    with transaction.atomic():
        token = ApiToken.objects.for_org(ctx.organization).select_for_update().get(id=token.id)
        if token.revoked_at is not None:
            return token
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "updated_at"])
        audit(
            ctx,
            "api_token.revoke",
            token,
            {
                "name": token.name,
                "kind": token.kind,
                "prefix": token.prefix,
                "site_id": token.site_id,
            },
        )
    return token


def view_api_tokens(ctx: RequestContext, site: Site) -> list[ApiToken]:
    require(ctx, Perm.API_TOKENS_MANAGE, site)
    return list_api_tokens(ctx.organization, site)
