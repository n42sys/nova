import pytest
from django.urls import reverse

from core.models import AuditLog, Organization, Role
from core.tests.factories import MembershipFactory, SiteRoleFactory

pytestmark = pytest.mark.django_db


def _url(org: Organization) -> str:
    return reverse("org-detail", kwargs={"org": org.slug})


@pytest.fixture
def org():
    return MembershipFactory(org_role=Role.OWNER).organization


def _login(browser, org, org_role):
    membership = MembershipFactory(organization=org, org_role=org_role)
    browser.force_login(membership.user)
    return membership


@pytest.mark.parametrize("org_role", [Role.OWNER, Role.ADMIN, Role.EDITOR, Role.EVENT_STAFF])
def test_any_member_can_view_org(browser, org, org_role):
    _login(browser, org, org_role)

    response = browser.get(_url(org))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(org.id),
        "slug": org.slug,
        "name": org.name,
        "status": "active",
        "features": {},
    }


def test_site_only_member_can_view_org(browser, org):
    site_role = SiteRoleFactory(membership__organization=org, membership__org_role=None)
    browser.force_login(site_role.membership.user)

    assert browser.get(_url(org)).status_code == 200


@pytest.mark.parametrize("org_role", [Role.OWNER, Role.ADMIN])
def test_owner_and_admin_can_rename(browser, org, org_role):
    membership = _login(browser, org, org_role)
    old_name = org.name

    response = browser.send("patch", _url(org), {"name": "Culture & Interest"})

    assert response.status_code == 200
    assert response.json()["name"] == "Culture & Interest"
    org.refresh_from_db()
    assert org.name == "Culture & Interest"
    entry = AuditLog.objects.for_org(org).get(action="org.update")
    assert entry.actor_user == membership.user
    assert entry.metadata == {"changes": {"name": {"from": old_name, "to": "Culture & Interest"}}}


@pytest.mark.parametrize("org_role", [Role.EDITOR, Role.EVENT_STAFF, None])
def test_others_cannot_rename(browser, org, org_role):
    if org_role is None:
        membership = SiteRoleFactory(
            membership__organization=org, membership__org_role=None, role=Role.ADMIN
        ).membership
        browser.force_login(membership.user)
    else:
        _login(browser, org, org_role)

    response = browser.send("patch", _url(org), {"name": "Nope"})

    assert response.status_code == 403
    org.refresh_from_db()
    assert org.name != "Nope"
    assert not AuditLog.objects.for_org(org).exists()


def test_unchanged_name_writes_no_audit(browser, org):
    _login(browser, org, Role.ADMIN)

    assert browser.send("patch", _url(org), {"name": org.name}).status_code == 200
    assert not AuditLog.objects.for_org(org).exists()


def test_blank_name_is_rejected(browser, org):
    _login(browser, org, Role.ADMIN)

    response = browser.send("patch", _url(org), {"name": ""})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"
