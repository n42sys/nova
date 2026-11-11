import pytest
from django.test import override_settings

from core.models import Organization, Role
from core.services import support
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
    UserFactory,
)
from core.tests.urls_org_scoped import ProbeView

pytestmark = [pytest.mark.django_db, pytest.mark.urls("core.tests.urls_org_scoped")]


def _probe(org_slug: str) -> str:
    return f"/api/manage/orgs/{org_slug}/probe/"


@pytest.fixture
def member(browser):
    membership = MembershipFactory(org_role=Role.ADMIN)
    browser.force_login(membership.user)
    return membership


def test_member_gets_context(browser, member):
    response = browser.get(_probe(member.organization.slug), REMOTE_ADDR="198.51.100.4")

    assert response.status_code == 200
    assert response.json() == {
        "org": member.organization.slug,
        "org_role": "admin",
        "ip": "198.51.100.4",
        "actor_type": "user",
    }


def test_non_member_gets_404_with_no_org_data(browser, member):
    org_b = OrganizationFactory(name="Org B Secret Name", slug="org-b")
    MembershipFactory(organization=org_b)

    response = browser.get(_probe(org_b.slug))

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not found.", "details": None}
    }
    assert b"org-b" not in response.content and b"Secret" not in response.content


def test_unknown_org_and_foreign_org_look_identical(browser, member):
    org_b = OrganizationFactory()

    foreign = browser.get(_probe(org_b.slug))
    unknown = browser.get(_probe("does-not-exist"))

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


def test_suspended_org_is_404_for_its_members(browser, member):
    Organization.objects.filter(id=member.organization_id).update(
        status=Organization.Status.SUSPENDED
    )

    assert browser.get(_probe(member.organization.slug)).status_code == 404


def test_staff_without_membership_get_404(browser):
    org = OrganizationFactory()
    browser.force_login(UserFactory(is_staff=True))

    assert browser.get(_probe(org.slug)).status_code == 404


def test_support_sessions_are_not_implemented():
    with pytest.raises(NotImplementedError):
        support.start_support_session(None, OrganizationFactory())


def test_anonymous_gets_401_even_for_unknown_org(browser):
    response = browser.get(_probe("does-not-exist"))

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Session realm="api"'
    assert response.json()["error"]["code"] == "not_authenticated"


def test_anonymous_write_gets_401(browser):
    org = OrganizationFactory()

    assert browser.send("post", _probe(org.slug)).status_code == 401


def test_unsafe_methods_require_csrf(browser, member):
    without_token = browser.post(_probe(member.organization.slug))
    with_token = browser.send("post", _probe(member.organization.slug))

    assert without_token.status_code == 403
    assert with_token.status_code == 200


def test_context_has_prefetched_site_roles(rf, django_assert_num_queries):
    site_role = SiteRoleFactory(membership__org_role=None, role=Role.EDITOR)
    other_site = SiteFactory(organization=site_role.organization)
    request = rf.get("/")
    request.user = site_role.membership.user

    ctx = ProbeView.build_context(request, site_role.organization.slug)

    with django_assert_num_queries(0):
        assert ctx.membership.effective_role(site_role.site) == Role.EDITOR
        assert ctx.membership.effective_role(other_site) is None


@override_settings(NOVA_TRUSTED_PROXY_COUNT=1)
def test_context_ip_uses_trusted_proxy_setting(browser, member):
    response = browser.get(
        _probe(member.organization.slug),
        REMOTE_ADDR="10.0.0.2",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9",
    )

    assert response.json()["ip"] == "203.0.113.9"
