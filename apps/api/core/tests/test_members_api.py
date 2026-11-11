from unittest import mock

import pytest
from django.urls import reverse

from core.context import ActorType, RequestContext
from core.exceptions import Conflict
from core.models import AuditLog, Membership, Role, SiteRole
from core.selectors.memberships import get_membership
from core.services.memberships import change_org_role, remove_member
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def owner(org):
    return MembershipFactory(organization=org, org_role=Role.OWNER)


@pytest.fixture
def site(org):
    return SiteFactory(organization=org, slug="main")


def _member(org, org_role=Role.EDITOR):
    return MembershipFactory(organization=org, org_role=org_role)


def _list_url(org):
    return reverse("member-list", kwargs={"org": org.slug})


def _detail_url(membership):
    return reverse(
        "member-detail",
        kwargs={"org": membership.organization.slug, "membership_id": membership.id},
    )


def _site_role_url(membership, site):
    return reverse(
        "member-site-role",
        kwargs={
            "org": membership.organization.slug,
            "membership_id": membership.id,
            "site_id": site.id,
        },
    )


def _as(browser, membership):
    browser.force_login(membership.user)
    return membership


def _ctx(membership) -> RequestContext:
    loaded = get_membership(membership.organization, membership.user)
    return RequestContext(
        user=loaded.user,
        membership=loaded,
        organization=loaded.organization,
        ip=None,
        actor_type=ActorType.USER,
    )


def _role(membership):
    return Membership.objects.for_org(membership.organization).get(id=membership.id).org_role


# List


def test_admin_lists_members_with_site_roles(browser, org, owner, site):
    admin = _as(browser, _member(org, Role.ADMIN))
    site_only = SiteRoleFactory(
        membership__organization=org, membership__org_role=None, site=site, role=Role.EDITOR
    ).membership

    response = browser.get(_list_url(org))

    assert response.status_code == 200
    by_id = {member["id"]: member for member in response.json()}
    assert set(by_id) == {str(owner.id), str(admin.id), str(site_only.id)}
    assert by_id[str(site_only.id)]["org_role"] is None
    assert by_id[str(site_only.id)]["site_roles"] == [
        {"site_id": str(site.id), "site_slug": "main", "site_name": site.name, "role": "editor"}
    ]
    assert by_id[str(owner.id)]["user"]["email"] == owner.user.email


@pytest.mark.parametrize("org_role", [Role.EDITOR, Role.EVENT_STAFF])
def test_members_view_needs_owner_or_admin(browser, org, owner, org_role):
    _as(browser, _member(org, org_role))

    assert browser.get(_list_url(org)).status_code == 403


# Change org role


def test_admin_changes_editor_to_event_staff_and_audits(browser, org, owner):
    admin = _as(browser, _member(org, Role.ADMIN))
    editor = _member(org, Role.EDITOR)

    response = browser.send("patch", _detail_url(editor), {"org_role": "event_staff"})

    assert response.status_code == 200
    assert response.json()["org_role"] == "event_staff"
    entry = AuditLog.objects.for_org(org).get(action="member.role_change")
    assert entry.actor_user == admin.user
    assert entry.metadata == {"user_id": str(editor.user_id), "from": "editor", "to": "event_staff"}


def test_org_role_can_be_cleared_to_site_only(browser, org, owner):
    _as(browser, owner)
    editor = _member(org)

    assert browser.send("patch", _detail_url(editor), {"org_role": None}).status_code == 200
    assert _role(editor) is None


# Rule: admins can't grant, change or remove owner


def test_admin_cannot_grant_owner(browser, org, owner):
    _as(browser, _member(org, Role.ADMIN))
    editor = _member(org)

    assert browser.send("patch", _detail_url(editor), {"org_role": "owner"}).status_code == 403
    assert _role(editor) == Role.EDITOR


def test_admin_cannot_change_an_owner(browser, org, owner):
    second_owner = _member(org, Role.OWNER)
    _as(browser, _member(org, Role.ADMIN))

    assert (
        browser.send("patch", _detail_url(second_owner), {"org_role": "editor"}).status_code == 403
    )
    assert _role(second_owner) == Role.OWNER


def test_admin_cannot_remove_an_owner(browser, org, owner):
    second_owner = _member(org, Role.OWNER)
    _as(browser, _member(org, Role.ADMIN))

    assert browser.send("delete", _detail_url(second_owner)).status_code == 403
    assert Membership.objects.for_org(org).filter(id=second_owner.id).exists()


def test_owner_can_grant_and_remove_owner(browser, org, owner):
    _as(browser, owner)
    editor = _member(org)

    assert browser.send("patch", _detail_url(editor), {"org_role": "owner"}).status_code == 200
    assert browser.send("patch", _detail_url(editor), {"org_role": "admin"}).status_code == 200
    assert _role(editor) == Role.ADMIN


# Rule: the last owner can't be demoted or removed


def test_last_owner_cannot_be_demoted_after_a_concurrent_demotion(org, owner):
    other_owner = _member(org, Role.OWNER)
    stale_ctx = _ctx(other_owner)  # other_owner's request started while still an owner
    change_org_role(_ctx(owner), other_owner, Role.ADMIN)  # ... then owner demoted them

    with pytest.raises(Conflict):
        change_org_role(stale_ctx, owner, Role.ADMIN)

    assert _role(owner) == Role.OWNER


def test_last_owner_cannot_be_removed_after_a_concurrent_demotion(org, owner):
    other_owner = _member(org, Role.OWNER)
    stale_ctx = _ctx(other_owner)
    change_org_role(_ctx(owner), other_owner, Role.ADMIN)

    with pytest.raises(Conflict):
        remove_member(stale_ctx, owner)

    assert Membership.objects.for_org(org).filter(id=owner.id).exists()


def test_sole_owner_cannot_demote_or_remove_themselves(browser, org, owner):
    _as(browser, owner)

    assert browser.send("patch", _detail_url(owner), {"org_role": "admin"}).status_code == 403
    assert browser.send("delete", _detail_url(owner)).status_code == 403
    assert _role(owner) == Role.OWNER


def test_one_of_two_owners_can_be_demoted(browser, org, owner):
    other_owner = _member(org, Role.OWNER)
    _as(browser, owner)

    assert browser.send("patch", _detail_url(other_owner), {"org_role": "admin"}).status_code == 200


# Rule: members can't change their own role


@pytest.mark.parametrize("org_role", [Role.OWNER, Role.ADMIN])
def test_members_cannot_change_their_own_membership(browser, org, owner, site, org_role):
    me = owner if org_role == Role.OWNER else _member(org, Role.ADMIN)
    _member(org, Role.OWNER)  # so `me` is never the last owner
    _as(browser, me)

    assert browser.send("patch", _detail_url(me), {"org_role": "editor"}).status_code == 403
    assert browser.send("delete", _detail_url(me)).status_code == 403
    assert browser.send("put", _site_role_url(me, site), {"role": "editor"}).status_code == 403
    assert browser.send("delete", _site_role_url(me, site)).status_code == 403
    assert _role(me) == org_role
    assert not AuditLog.objects.for_org(org).exists()


# Rule: promoting to owner deletes site roles in the same transaction


def test_promotion_to_owner_deletes_site_roles(browser, org, owner, site):
    events = SiteFactory(organization=org, slug="events")
    member = _member(org, None)
    SiteRoleFactory(membership=member, site=site, role=Role.EDITOR)
    SiteRoleFactory(membership=member, site=events, role=Role.EVENT_STAFF)
    _as(browser, owner)

    response = browser.send("patch", _detail_url(member), {"org_role": "owner"})

    assert response.status_code == 200
    assert response.json()["site_roles"] == []
    assert not SiteRole.objects.for_org(org).filter(membership=member).exists()
    entry = AuditLog.objects.for_org(org).get(action="member.role_change")
    assert sorted(entry.metadata["removed_site_roles"], key=lambda r: r["role"]) == [
        {"site_id": str(site.id), "role": "editor"},
        {"site_id": str(events.id), "role": "event_staff"},
    ]


def test_promotion_rolls_back_with_site_roles_if_audit_fails(org, owner, site):
    member = _member(org, None)
    SiteRoleFactory(membership=member, site=site, role=Role.EDITOR)

    with (
        mock.patch("core.services.memberships.audit", side_effect=RuntimeError("audit down")),
        pytest.raises(RuntimeError),
    ):
        change_org_role(_ctx(owner), member, Role.OWNER)

    assert _role(member) is None
    assert SiteRole.objects.for_org(org).filter(membership=member).count() == 1


# Remove


def test_remove_member_deletes_membership_and_site_roles(browser, org, owner, site):
    member = SiteRoleFactory(membership__organization=org, site=site).membership
    _as(browser, _member(org, Role.ADMIN))

    assert browser.send("delete", _detail_url(member)).status_code == 204
    assert not Membership.objects.for_org(org).filter(id=member.id).exists()
    assert not SiteRole.objects.for_org(org).filter(membership_id=member.id).exists()
    entry = AuditLog.objects.for_org(org).get(action="member.remove")
    assert entry.target_id == str(member.id)
    assert entry.metadata["site_roles"] == [{"site_id": str(site.id), "role": "editor"}]


@pytest.mark.parametrize("org_role", [Role.EDITOR, Role.EVENT_STAFF])
def test_non_managers_cannot_change_members(browser, org, owner, org_role):
    _as(browser, _member(org, org_role))
    target = _member(org)

    assert browser.send("patch", _detail_url(target), {"org_role": "admin"}).status_code == 403
    assert browser.send("delete", _detail_url(target)).status_code == 403


def test_site_admin_role_does_not_grant_member_management(browser, org, owner, site):
    _as(
        browser,
        SiteRoleFactory(
            membership__organization=org, membership__org_role=None, site=site, role=Role.ADMIN
        ).membership,
    )
    target = _member(org)

    assert browser.send("patch", _detail_url(target), {"org_role": "admin"}).status_code == 403


# Site roles


def test_set_change_and_remove_site_role(browser, org, owner, site):
    _as(browser, _member(org, Role.ADMIN))
    member = _member(org, None)
    url = _site_role_url(member, site)

    response = browser.send("put", url, {"role": "editor"})
    assert response.status_code == 200
    assert response.json()["site_roles"][0]["role"] == "editor"
    assert browser.send("put", url, {"role": "event_staff"}).status_code == 200
    assert browser.send("put", url, {"role": "event_staff"}).status_code == 200  # no-op
    assert browser.send("delete", url).status_code == 204
    assert browser.send("delete", url).status_code == 204  # idempotent

    actions = list(
        AuditLog.objects.for_org(org).order_by("created_at", "id").values_list("action", "metadata")
    )
    assert [
        (action, meta.get("from"), meta.get("to", meta.get("role"))) for action, meta in actions
    ] == [
        ("member.site_role_set", None, "editor"),
        ("member.site_role_set", "editor", "event_staff"),
        ("member.site_role_remove", None, "event_staff"),
    ]


def test_owner_role_cannot_be_set_on_a_site(browser, org, owner, site):
    _as(browser, _member(org, Role.ADMIN))
    member = _member(org, None)

    response = browser.send("put", _site_role_url(member, site), {"role": "owner"})

    assert response.status_code == 400
    assert not SiteRole.objects.for_org(org).exists()


def test_owners_cannot_be_given_site_roles(browser, org, owner, site):
    other_owner = _member(org, Role.OWNER)
    _as(browser, owner)

    assert (
        browser.send("put", _site_role_url(other_owner, site), {"role": "editor"}).status_code
        == 400
    )


# Strict admin scope: admins manage only roles below their own


@pytest.mark.parametrize(
    ("org_role", "expected"),
    [("editor", 200), ("event_staff", 200), (None, 200), ("admin", 403), ("owner", 403)],
)
def test_admin_grants_only_roles_below_admin_as_org_role(browser, org, owner, org_role, expected):
    _as(browser, _member(org, Role.ADMIN))
    member = _member(org, Role.EVENT_STAFF if org_role == "editor" else Role.EDITOR)
    before = _role(member)

    response = browser.send("patch", _detail_url(member), {"org_role": org_role})

    assert response.status_code == expected
    assert _role(member) == (org_role if expected == 200 else before)


@pytest.mark.parametrize(
    ("role", "expected"), [("editor", 200), ("event_staff", 200), ("admin", 403)]
)
def test_admin_grants_only_roles_below_admin_as_site_role(
    browser, org, owner, site, role, expected
):
    _as(browser, _member(org, Role.ADMIN))
    member = _member(org, None)

    response = browser.send("put", _site_role_url(member, site), {"role": role})

    assert response.status_code == expected
    assert SiteRole.objects.for_org(org).filter(membership=member).exists() == (expected == 200)


@pytest.mark.parametrize("target_role", [Role.ADMIN, Role.OWNER])
def test_admin_cannot_touch_admins_or_owners(browser, org, owner, site, target_role):
    _as(browser, _member(org, Role.ADMIN))
    target = owner if target_role == Role.OWNER else _member(org, Role.ADMIN)

    assert browser.send("patch", _detail_url(target), {"org_role": "editor"}).status_code == 403
    assert browser.send("delete", _detail_url(target)).status_code == 403
    assert browser.send("put", _site_role_url(target, site), {"role": "editor"}).status_code == 403
    assert browser.send("delete", _site_role_url(target, site)).status_code == 403
    assert _role(target) == target_role
    assert not AuditLog.objects.for_org(org).exists()


def test_admin_cannot_change_or_remove_an_admin_site_role(browser, org, owner, site):
    site_admin = SiteRoleFactory(
        membership__organization=org, membership__org_role=None, site=site, role=Role.ADMIN
    ).membership
    _as(browser, _member(org, Role.ADMIN))

    assert (
        browser.send("put", _site_role_url(site_admin, site), {"role": "editor"}).status_code == 403
    )
    assert browser.send("delete", _site_role_url(site_admin, site)).status_code == 403
    assert browser.send("delete", _detail_url(site_admin)).status_code == 403
    assert SiteRole.objects.for_org(org).get(membership=site_admin).role == Role.ADMIN


def test_owner_grants_changes_and_removes_admin(browser, org, owner, site):
    _as(browser, owner)
    editor, site_only = _member(org, Role.EDITOR), _member(org, None)

    assert browser.send("patch", _detail_url(editor), {"org_role": "admin"}).status_code == 200
    assert browser.send("patch", _detail_url(editor), {"org_role": "editor"}).status_code == 200
    assert browser.send("patch", _detail_url(editor), {"org_role": "admin"}).status_code == 200
    assert (
        browser.send("put", _site_role_url(site_only, site), {"role": "admin"}).status_code == 200
    )
    assert (
        browser.send("put", _site_role_url(site_only, site), {"role": "editor"}).status_code == 200
    )
    assert browser.send("delete", _site_role_url(site_only, site)).status_code == 204
    assert browser.send("delete", _detail_url(editor)).status_code == 204
    assert not Membership.objects.for_org(org).filter(id=editor.id).exists()


def test_admin_still_manages_members_below_admin(browser, org, owner, site):
    _as(browser, _member(org, Role.ADMIN))
    member = _member(org, Role.EVENT_STAFF)

    assert browser.send("put", _site_role_url(member, site), {"role": "editor"}).status_code == 200
    assert browser.send("delete", _site_role_url(member, site)).status_code == 204
    assert browser.send("delete", _detail_url(member)).status_code == 204
