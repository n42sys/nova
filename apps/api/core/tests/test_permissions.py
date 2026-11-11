"""Permission matrix test.

ROLE_TABLE is a literal copy of the role table in docs/design/phase-1-core-design.md. The
expected allow/deny for every (Role, Perm) pair comes from this table and PERM_ROWS only; it
never reads ROLE_PERMS. `test_role_table_matches_design_doc` fails if the doc and this copy drift.
"""

from pathlib import Path

import pytest
from django.conf import settings

from core.context import ActorType, RequestContext
from core.exceptions import PermissionDenied
from core.models import Membership, Organization, Role
from core.permissions import ORG_ONLY_PERMS, Perm, require
from core.selectors.memberships import get_membership
from core.tests.factories import SiteFactory, SiteRoleFactory

DESIGN_DOC = Path(settings.BASE_DIR).parent.parent / "docs/design/phase-1-core-design.md"

ROLE_TABLE = """
| Action | Owner | Admin | Editor | Event staff |
| --- | --- | --- | --- | --- |
| View sites and content | Yes | Yes | Yes | Assigned events only |
| Create and edit content, forms, events | Yes | Yes | Yes | No |
| Publish and unpublish | Yes | Yes | Yes | No |
| Upload media | Yes | Yes | Yes | No |
| Delete media | Yes | Yes | No | No |
| View form submissions and attendee lists | Yes | Yes | Yes | Assigned events only |
| Check in tickets | Yes | Yes | Yes | Yes |
| Create sites, change site settings | Yes | Yes | No | No |
| Create and revoke API tokens | Yes | Yes | No | No |
| Edit organization details (org-only) | Yes | Yes | No | No |
| View members (org-only) | Yes | Yes | No | No |
| Invite members, change roles below own (org-only) | Yes | Yes (not to owner) | No | No |
| View audit log (org-only) | Yes | Yes | No | No |
| Add or change payment accounts (org-only) | Yes | No | No | No |
| Transfer ownership, delete organization (org-only) | Yes | No | No | No |
"""

ASSIGNED = "Assigned events only"

# Perm value -> (table row it implements, whether an "Assigned events only" cell grants it).
# A narrow *_assigned perm is granted wherever the broad one is; services filter to the
# member's assigned events unless the broad perm is also held.
PERM_ROWS: dict[str, tuple[str, bool]] = {
    "site.view": ("View sites and content", True),
    "content.view": ("View sites and content", False),
    "forms.view": ("View sites and content", False),
    "events.view": ("View sites and content", False),
    "events.view_assigned": ("View sites and content", True),
    "content.edit": ("Create and edit content, forms, events", False),
    "forms.edit": ("Create and edit content, forms, events", False),
    "events.edit": ("Create and edit content, forms, events", False),
    "content.publish": ("Publish and unpublish", False),
    "forms.publish": ("Publish and unpublish", False),
    "events.publish": ("Publish and unpublish", False),
    "media.upload": ("Upload media", False),
    "media.delete": ("Delete media", False),
    "forms.submissions.view": ("View form submissions and attendee lists", False),
    "events.attendees.view": ("View form submissions and attendee lists", False),
    "events.attendees.view_assigned": ("View form submissions and attendee lists", True),
    "tickets.check_in": ("Check in tickets", False),
    "sites.manage": ("Create sites, change site settings", False),
    "api_tokens.manage": ("Create and revoke API tokens", False),
    "org.manage": ("Edit organization details (org-only)", False),
    "members.view": ("View members (org-only)", False),
    "members.manage": ("Invite members, change roles below own (org-only)", False),
    "audit.view": ("View audit log (org-only)", False),
    "payments.manage": ("Add or change payment accounts (org-only)", False),
    "org.transfer_ownership": ("Transfer ownership, delete organization (org-only)", False),
    "org.delete": ("Transfer ownership, delete organization (org-only)", False),
}

COLUMNS = ("owner", "admin", "editor", "event_staff")


def _parse(table: str) -> dict[str, dict[str, str]]:
    rows = {}
    for line in table.strip().splitlines()[2:]:
        action, *cells = (cell.strip() for cell in line.strip().strip("|").split("|"))
        rows[action] = dict(zip(COLUMNS, cells, strict=True))
    return rows


ROWS = _parse(ROLE_TABLE)


def _expected(perm_value: str, role: str) -> bool:
    row, assigned_grants = PERM_ROWS[perm_value]
    cell = ROWS[row][role]
    if cell == "Yes" or cell.startswith("Yes ("):
        return True
    if cell == "No":
        return False
    if cell == ASSIGNED:
        return assigned_grants
    raise AssertionError(f"Unknown cell {cell!r} in row {row!r}")


def _ctx(org_role: Role | None) -> RequestContext:
    return RequestContext(
        user=None,
        membership=Membership(org_role=org_role),
        organization=Organization(),
        ip=None,
        actor_type=ActorType.USER,
    )


def test_role_table_matches_design_doc():
    assert ROLE_TABLE.strip() in DESIGN_DOC.read_text()


def test_every_perm_is_mapped_to_a_row():
    assert set(PERM_ROWS) == {perm.value for perm in Perm}
    assert {row for row, _ in PERM_ROWS.values()} == set(ROWS)


def test_org_only_perms_match_the_table():
    expected = {value for value, (row, _) in PERM_ROWS.items() if "(org-only)" in row}

    assert {perm.value for perm in ORG_ONLY_PERMS} == expected


@pytest.mark.parametrize("perm_value", sorted(PERM_ROWS))
@pytest.mark.parametrize("role", COLUMNS)
def test_matrix(role, perm_value):
    ctx = _ctx(Role(role))

    if _expected(perm_value, role):
        require(ctx, Perm(perm_value))
    else:
        with pytest.raises(PermissionDenied):
            require(ctx, Perm(perm_value))


@pytest.mark.parametrize("perm", list(Perm))
def test_no_role_means_no_access(perm):
    with pytest.raises(PermissionDenied):
        require(_ctx(None), perm)


# Site resolution (DB-backed: roles come from real Membership/SiteRole rows)


def _ctx_for(membership: Membership) -> RequestContext:
    loaded = get_membership(membership.organization, membership.user)
    return RequestContext(
        user=loaded.user,
        membership=loaded,
        organization=loaded.organization,
        ip=None,
        actor_type=ActorType.USER,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("site_role", [Role.EVENT_STAFF, Role.ADMIN])
@pytest.mark.parametrize("perm", sorted(ORG_ONLY_PERMS))
def test_org_only_perm_ignores_site_override(site_role, perm):
    site_role_row = SiteRoleFactory(membership__org_role=None, role=site_role)
    ctx = _ctx_for(site_role_row.membership)

    with pytest.raises(PermissionDenied):
        require(ctx, perm, site_role_row.site)


@pytest.mark.django_db
def test_event_staff_site_role_cannot_reach_payments_manage():
    site_role = SiteRoleFactory(membership__org_role=None, role=Role.EVENT_STAFF)
    ctx = _ctx_for(site_role.membership)

    require(ctx, Perm.TICKETS_CHECK_IN, site_role.site)
    with pytest.raises(PermissionDenied):
        require(ctx, Perm.PAYMENTS_MANAGE, site_role.site)


@pytest.mark.django_db
def test_site_role_on_a_is_denied_on_b():
    site_role = SiteRoleFactory(membership__org_role=None, role=Role.EDITOR)
    site_b = SiteFactory(organization=site_role.organization)
    ctx = _ctx_for(site_role.membership)

    require(ctx, Perm.CONTENT_EDIT, site_role.site)
    with pytest.raises(PermissionDenied):
        require(ctx, Perm.CONTENT_EDIT, site_b)
    with pytest.raises(PermissionDenied):
        require(ctx, Perm.SITE_VIEW, site_b)


@pytest.mark.django_db
def test_site_role_overrides_org_role_downwards():
    site_role = SiteRoleFactory(membership__org_role=Role.ADMIN, role=Role.EVENT_STAFF)
    other_site = SiteFactory(organization=site_role.organization)
    ctx = _ctx_for(site_role.membership)

    with pytest.raises(PermissionDenied):
        require(ctx, Perm.CONTENT_EDIT, site_role.site)
    require(ctx, Perm.CONTENT_EDIT, other_site)
    require(ctx, Perm.MEMBERS_MANAGE, site_role.site)  # org-only: still the org admin role


def test_token_or_system_actor_without_membership_is_denied():
    ctx = RequestContext(
        user=None, membership=None, organization=Organization(), ip=None, actor_type=ActorType.TOKEN
    )

    with pytest.raises(PermissionDenied):
        require(ctx, Perm.SITE_VIEW)
