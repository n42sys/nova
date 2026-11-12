from unittest import mock

import pytest
from django.urls import reverse

from core.context import ActorType, RequestContext
from core.exceptions import ValidationFailed
from core.models import AuditLog, Organization, Role, Site
from core.permissions import Perm
from core.services.sites import create_site, update_site
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
)

pytestmark = pytest.mark.django_db


def _list_url(org: Organization) -> str:
    return reverse("site-list", kwargs={"org": org.slug})


def _detail_url(site: Site) -> str:
    return reverse("site-detail", kwargs={"org": site.organization.slug, "site_id": site.id})


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def sites(org):
    return {
        slug: SiteFactory(organization=org, slug=slug, name=name)
        for slug, name in [("main", "A Main"), ("events", "B Events"), ("shop", "C Shop")]
    }


def _member(browser, org, org_role=None, site_roles=None):
    membership = MembershipFactory(organization=org, org_role=org_role)
    for site, role in (site_roles or {}).items():
        SiteRoleFactory(membership=membership, site=site, role=role)
    browser.force_login(membership.user)
    return membership


# List


@pytest.mark.parametrize("org_role", [Role.OWNER, Role.ADMIN, Role.EDITOR, Role.EVENT_STAFF])
def test_org_roles_see_all_active_sites(browser, org, sites, org_role):
    _member(browser, org, org_role)

    response = browser.get(_list_url(org))

    assert response.status_code == 200
    assert [site["slug"] for site in response.json()] == ["main", "events", "shop"]


def test_site_only_member_sees_only_their_sites(browser, org, sites):
    _member(browser, org, None, {sites["main"]: Role.EDITOR, sites["events"]: Role.EVENT_STAFF})

    response = browser.get(_list_url(org))

    assert [site["slug"] for site in response.json()] == ["main", "events"]


def test_archived_sites_are_not_listed(browser, org, sites):
    sites["shop"].status = Site.Status.ARCHIVED
    sites["shop"].save()
    _member(browser, org, Role.OWNER)

    assert [site["slug"] for site in browser.get(_list_url(org)).json()] == ["main", "events"]


# Create


@pytest.mark.parametrize("org_role", [Role.OWNER, Role.ADMIN])
def test_owner_and_admin_create_sites(browser, org, org_role):
    membership = _member(browser, org, org_role)

    response = browser.send("post", _list_url(org), {"name": "Listening Room", "slug": "listening"})

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "listening"
    assert body["timezone"] == "Africa/Nairobi"
    assert body["default_locale"] == "en"
    assert body["status"] == "active"
    site = Site.objects.for_org(org).get(slug="listening")
    entry = AuditLog.objects.for_org(org).get(action="site.create")
    assert (entry.target_id, entry.actor_user) == (str(site.id), membership.user)


def test_create_with_all_fields(browser, org):
    _member(browser, org, Role.ADMIN)

    response = browser.send(
        "post",
        _list_url(org),
        {
            "name": "Screenings",
            "slug": "screenings",
            "timezone": "Europe/London",
            "default_locale": "sw",
            "settings": {"theme": "dark"},
        },
    )

    assert response.status_code == 201
    site = Site.objects.for_org(org).get(slug="screenings")
    assert (site.timezone, site.default_locale, site.settings) == (
        "Europe/London",
        "sw",
        {"theme": "dark"},
    )


def test_editor_cannot_create_sites(browser, org):
    _member(browser, org, Role.EDITOR)

    assert browser.send("post", _list_url(org), {"name": "X", "slug": "x"}).status_code == 403
    assert not Site.objects.for_org(org).exists()


def test_site_admin_without_org_role_cannot_create_sites(browser, org, sites):
    _member(browser, org, None, {sites["main"]: Role.ADMIN})

    assert browser.send("post", _list_url(org), {"name": "X", "slug": "x"}).status_code == 403


def test_duplicate_slug_in_org_is_409(browser, org, sites):
    _member(browser, org, Role.ADMIN)

    response = browser.send("post", _list_url(org), {"name": "Again", "slug": "main"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_slug_may_repeat_across_orgs(browser, org, sites):
    other = OrganizationFactory()
    _member(browser, other, Role.ADMIN)

    assert browser.send("post", _list_url(other), {"name": "M", "slug": "main"}).status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"name": "X", "slug": "x", "timezone": "Mars/Olympus"},
        {"name": "X", "slug": "x", "timezone": "nairobi"},
        {"name": "X", "slug": "not a slug"},
        {"name": "", "slug": "x"},
        {"name": "X", "slug": "x", "settings": ["not", "an", "object"]},
    ],
)
def test_invalid_input_is_400(browser, org, body):
    _member(browser, org, Role.ADMIN)

    response = browser.send("post", _list_url(org), body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"
    assert not Site.objects.for_org(org).exists()


def test_failed_audit_rolls_back_the_write(browser, org):
    _member(browser, org, Role.ADMIN)

    with (
        mock.patch("core.services.sites.audit", side_effect=RuntimeError("audit down")),
        pytest.raises(RuntimeError),
    ):
        browser.send("post", _list_url(org), {"name": "X", "slug": "x"})

    assert not Site.objects.for_org(org).exists()


# Retrieve


def test_retrieve_visible_site(browser, org, sites):
    _member(browser, org, None, {sites["events"]: Role.EVENT_STAFF})

    response = browser.get(_detail_url(sites["events"]))

    assert response.status_code == 200
    assert response.json()["id"] == str(sites["events"].id)


def test_site_without_access_is_404(browser, org, sites):
    _member(browser, org, None, {sites["events"]: Role.EVENT_STAFF})

    assert browser.get(_detail_url(sites["main"])).status_code == 404


# Update


def test_admin_updates_site_and_audit_records_diff(browser, org, sites):
    _member(browser, org, Role.ADMIN)
    site = sites["main"]

    response = browser.send(
        "patch", _detail_url(site), {"name": "Main Stage", "timezone": "Europe/London"}
    )

    assert response.status_code == 200
    site.refresh_from_db()
    assert (site.name, site.timezone) == ("Main Stage", "Europe/London")
    entry = AuditLog.objects.for_org(org).get(action="site.update")
    assert entry.metadata == {
        "changes": {
            "name": {"from": "A Main", "to": "Main Stage"},
            "timezone": {"from": "Africa/Nairobi", "to": "Europe/London"},
        }
    }


def test_site_admin_role_can_manage_only_that_site(browser, org, sites):
    _member(browser, org, None, {sites["main"]: Role.ADMIN, sites["events"]: Role.EDITOR})

    assert browser.send("patch", _detail_url(sites["main"]), {"name": "Ok"}).status_code == 200
    assert browser.send("patch", _detail_url(sites["events"]), {"name": "No"}).status_code == 403
    assert browser.send("patch", _detail_url(sites["shop"]), {"name": "No"}).status_code == 404


def test_editor_cannot_update_site(browser, org, sites):
    _member(browser, org, Role.EDITOR)

    assert browser.send("patch", _detail_url(sites["main"]), {"name": "No"}).status_code == 403


def test_update_rejects_unknown_timezone_and_taken_slug(browser, org, sites):
    _member(browser, org, Role.ADMIN)
    url = _detail_url(sites["main"])

    assert browser.send("patch", url, {"timezone": "Nowhere/Town"}).status_code == 400
    assert browser.send("patch", url, {"slug": "events"}).status_code == 409
    sites["main"].refresh_from_db()
    assert (sites["main"].slug, sites["main"].timezone) == ("main", "Africa/Nairobi")


def test_domain_and_status_are_not_writable(browser, org, sites):
    _member(browser, org, Role.ADMIN)

    browser.send(
        "patch", _detail_url(sites["main"]), {"domain": "evil.example", "status": "archived"}
    )

    sites["main"].refresh_from_db()
    assert (sites["main"].domain, sites["main"].status) == (None, Site.Status.ACTIVE)


# Archive (soft delete)


def test_delete_archives_the_site(browser, org, sites):
    _member(browser, org, Role.ADMIN)
    site = sites["shop"]

    assert browser.send("delete", _detail_url(site)).status_code == 204
    site.refresh_from_db()
    assert site.status == Site.Status.ARCHIVED
    assert AuditLog.objects.for_org(org).filter(action="site.archive").count() == 1

    assert browser.send("delete", _detail_url(site)).status_code == 204  # idempotent
    assert AuditLog.objects.for_org(org).filter(action="site.archive").count() == 1
    assert browser.get(_detail_url(site)).json()["status"] == "archived"


def test_editor_cannot_archive(browser, org, sites):
    _member(browser, org, Role.EDITOR)

    assert browser.send("delete", _detail_url(sites["main"])).status_code == 403
    sites["main"].refresh_from_db()
    assert sites["main"].status == Site.Status.ACTIVE


# Service-level timezone validation


@pytest.mark.parametrize("timezone", ["Mars/Olympus", "nairobi", "Africa/nairobi", ""])
def test_site_service_rejects_timezones_outside_zoneinfo(org, timezone):
    owner = MembershipFactory(organization=org, org_role=Role.OWNER)
    ctx = RequestContext(
        user=owner.user, membership=owner, organization=org, ip=None, actor_type=ActorType.USER
    )
    site = SiteFactory(organization=org)

    with pytest.raises(ValidationFailed):
        create_site(ctx, name="X", slug="x", timezone=timezone)
    with pytest.raises(ValidationFailed):
        update_site(ctx, site, timezone=timezone)
    assert create_site(ctx, name="Y", slug="y", timezone="America/Port_of_Spain").timezone == (
        "America/Port_of_Spain"
    )


# Caller permissions reported with each site (for the admin UI; the API still enforces)


def test_sites_report_the_callers_permissions_per_site(browser, org, sites):
    _member(browser, org, None, {sites["main"]: Role.ADMIN, sites["events"]: Role.EVENT_STAFF})

    by_slug = {
        site["slug"]: set(site["permissions"]) for site in browser.get(_list_url(org)).json()
    }

    assert {"sites.manage", "api_tokens.manage", "content.edit"} <= by_slug["main"]
    assert by_slug["events"] == {
        "site.view",
        "events.view_assigned",
        "events.attendees.view_assigned",
        "tickets.check_in",
    }
    assert "members.manage" not in by_slug["main"]  # org-only perms never come from a site role
    detail = browser.get(_detail_url(sites["events"])).json()
    assert set(detail["permissions"]) == by_slug["events"]


def test_owner_permissions_on_a_site_include_everything(browser, org, sites):
    _member(browser, org, Role.OWNER)

    permissions = browser.get(_detail_url(sites["main"])).json()["permissions"]

    assert set(permissions) == {perm.value for perm in Perm}
