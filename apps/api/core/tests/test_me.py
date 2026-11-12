import pytest

from core.models import Organization, Role
from core.tests.factories import MembershipFactory, OrganizationFactory, SiteRoleFactory

pytestmark = pytest.mark.django_db

ME = "/api/manage/me/"


def test_me_lists_orgs_with_roles_and_status(browser):
    site_role = SiteRoleFactory(
        membership__org_role=None,
        membership__organization__name="Culture & Interest",
        role=Role.EVENT_STAFF,
    )
    user = site_role.membership.user
    suspended = MembershipFactory(
        user=user,
        org_role=Role.ADMIN,
        organization=OrganizationFactory(name="Zeta", status=Organization.Status.SUSPENDED),
    )
    MembershipFactory()  # someone else's membership
    browser.force_login(user)

    response = browser.get(ME)

    assert response.status_code == 200
    org = site_role.organization
    body = response.json()
    site_only_perms, admin_perms = (o.pop("permissions") for o in body["organizations"])
    assert site_only_perms == []  # no org role: everything comes per site
    assert {"members.manage", "sites.manage", "audit.view"} <= set(admin_perms)
    assert "payments.manage" not in admin_perms
    assert body == {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "organizations": [
            {
                "id": str(org.id),
                "slug": org.slug,
                "name": "Culture & Interest",
                "status": "active",
                "org_role": None,
                "site_roles": [
                    {
                        "site_id": str(site_role.site.id),
                        "site_slug": site_role.site.slug,
                        "site_name": site_role.site.name,
                        "role": "event_staff",
                    }
                ],
            },
            {
                "id": str(suspended.organization.id),
                "slug": suspended.organization.slug,
                "name": "Zeta",
                "status": "suspended",
                "org_role": "admin",
                "site_roles": [],
            },
        ],
    }


def test_me_query_count_does_not_grow_with_orgs(browser, django_assert_max_num_queries):
    membership = MembershipFactory()
    for _ in range(5):
        SiteRoleFactory(membership=MembershipFactory(user=membership.user, org_role=None))
    browser.force_login(membership.user)

    with django_assert_max_num_queries(6):
        response = browser.get(ME)
    assert len(response.json()["organizations"]) == 6


def test_me_requires_authentication(browser):
    response = browser.get(ME)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Session realm="api"'
