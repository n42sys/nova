from django.db import transaction

from core.audit import audit
from core.context import RequestContext
from core.models import Organization
from core.permissions import Perm, require
from core.services._changes import apply_changes


def update_organization(ctx: RequestContext, *, name: str) -> Organization:
    require(ctx, Perm.ORG_MANAGE)
    org = ctx.organization
    with transaction.atomic():
        diff = apply_changes(org, {"name": name})
        if diff:
            org.save(update_fields=[*diff, "updated_at"])
            audit(ctx, "org.update", org, {"changes": diff})
    return org
