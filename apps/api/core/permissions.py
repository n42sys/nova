from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from core.exceptions import PermissionDenied
from core.models import Role

if TYPE_CHECKING:
    from core.context import RequestContext
    from core.models import Site


class Perm(StrEnum):
    """Every action in the design doc's role matrix, including modules built in later phases.

    Site-scoped perms resolve through `Membership.effective_role(site)`. Perms in
    `ORG_ONLY_PERMS` always use `Membership.org_role`.
    """

    # Sites
    SITE_VIEW = "site.view"
    SITES_MANAGE = "sites.manage"

    # Content (Phase 5)
    CONTENT_VIEW = "content.view"
    CONTENT_EDIT = "content.edit"
    CONTENT_PUBLISH = "content.publish"

    # Forms (Phase 2)
    FORMS_VIEW = "forms.view"
    FORMS_EDIT = "forms.edit"
    FORMS_PUBLISH = "forms.publish"
    FORM_SUBMISSIONS_VIEW = "forms.submissions.view"

    # Events and tickets (Phases 3-4)
    EVENTS_VIEW = "events.view"
    EVENTS_VIEW_ASSIGNED = "events.view_assigned"
    EVENTS_EDIT = "events.edit"
    EVENTS_PUBLISH = "events.publish"
    ATTENDEES_VIEW = "events.attendees.view"
    ATTENDEES_VIEW_ASSIGNED = "events.attendees.view_assigned"
    TICKETS_CHECK_IN = "tickets.check_in"

    # Media
    MEDIA_UPLOAD = "media.upload"
    MEDIA_DELETE = "media.delete"

    # API tokens
    API_TOKENS_MANAGE = "api_tokens.manage"

    # Organization (org-only)
    ORG_MANAGE = "org.manage"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"
    AUDIT_VIEW = "audit.view"
    PAYMENTS_MANAGE = "payments.manage"
    ORG_TRANSFER_OWNERSHIP = "org.transfer_ownership"
    ORG_DELETE = "org.delete"


# Single source of truth for who may do what; mirrors the role table in
# docs/design/phase-1-core-design.md. Owner ⊃ admin ⊃ editor; event staff is a narrow side role.
_EVENT_STAFF = frozenset(
    {
        Perm.SITE_VIEW,
        Perm.EVENTS_VIEW_ASSIGNED,
        Perm.ATTENDEES_VIEW_ASSIGNED,
        Perm.TICKETS_CHECK_IN,
    }
)

_EDITOR = frozenset(
    {
        Perm.SITE_VIEW,
        Perm.CONTENT_VIEW,
        Perm.CONTENT_EDIT,
        Perm.CONTENT_PUBLISH,
        Perm.FORMS_VIEW,
        Perm.FORMS_EDIT,
        Perm.FORMS_PUBLISH,
        Perm.FORM_SUBMISSIONS_VIEW,
        Perm.EVENTS_VIEW,
        Perm.EVENTS_VIEW_ASSIGNED,
        Perm.EVENTS_EDIT,
        Perm.EVENTS_PUBLISH,
        Perm.ATTENDEES_VIEW,
        Perm.ATTENDEES_VIEW_ASSIGNED,
        Perm.TICKETS_CHECK_IN,
        Perm.MEDIA_UPLOAD,
    }
)

_ADMIN = _EDITOR | {
    Perm.MEDIA_DELETE,
    Perm.SITES_MANAGE,
    Perm.API_TOKENS_MANAGE,
    Perm.ORG_MANAGE,
    Perm.MEMBERS_VIEW,
    Perm.MEMBERS_MANAGE,  # granting or removing owner is refused in the member service
    Perm.AUDIT_VIEW,
}

_OWNER = _ADMIN | {
    Perm.PAYMENTS_MANAGE,
    Perm.ORG_TRANSFER_OWNERSHIP,
    Perm.ORG_DELETE,
}

ROLE_PERMS: dict[Role, frozenset[Perm]] = {
    Role.OWNER: _OWNER,
    Role.ADMIN: _ADMIN,
    Role.EDITOR: _EDITOR,
    Role.EVENT_STAFF: _EVENT_STAFF,
}

# Always checked against `Membership.org_role`; a site role can never grant these.
ORG_ONLY_PERMS: frozenset[Perm] = frozenset(
    {
        Perm.ORG_MANAGE,
        Perm.MEMBERS_VIEW,
        Perm.MEMBERS_MANAGE,
        Perm.AUDIT_VIEW,
        Perm.PAYMENTS_MANAGE,
        Perm.ORG_TRANSFER_OWNERSHIP,
        Perm.ORG_DELETE,
    }
)


def require(ctx: RequestContext, perm: Perm, site: Site | None = None) -> None:
    """Raise PermissionDenied unless the acting member holds `perm` (on `site`, if given).

    Org-only perms, and checks without a site, use `org_role`. Otherwise the role resolves
    per site: SiteRole -> org_role -> no access. Callers must already have scoped `site`
    to `ctx.organization` (cross-tenant lookups are a 404 before this point).
    """
    membership = ctx.membership
    if membership is None:
        raise PermissionDenied(details={"permission": perm.value})

    if perm in ORG_ONLY_PERMS or site is None:
        role = Role(membership.org_role) if membership.org_role else None
    else:
        role = membership.effective_role(site)

    if role is None or perm not in ROLE_PERMS[role]:
        raise PermissionDenied(details={"permission": perm.value})
