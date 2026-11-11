"""Tenant isolation suite.

Two organizations, A and B, hold identical data. Every management endpoint is called by a
member of A against B: with B's org slug; with A's slug but B's object IDs; and, for URLs
with several IDs, with A's slug and A's IDs except one taken from B. Each call must return
the standard 404 body, contain no B data and change nothing in A or B.

Every route under /api/manage/ must be registered in ENDPOINTS (or EXEMPT, with a reason);
the coverage tests fail otherwise, including when a view gains an unregistered method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from core.models import AuditLog, Membership, Organization, Role, Site, SiteRole
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
    UserFactory,
)

MANAGE_PREFIX = "api/manage/"
NOT_FOUND = {"error": {"code": "not_found", "message": "Not found.", "details": None}}
HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# Members of A who make the cross-tenant calls: the strongest org role (so a 404 is never a
# masked 403) and a site-only member (whose site visibility is resolved differently).
ACTORS = ("owner", "site_only")


# Registry


@dataclass(frozen=True)
class Endpoint:
    name: str  # URL name
    kwargs: tuple[str, ...]  # URL kwargs, resolved per tenant by Tenant.url_kwargs()
    methods: dict[str, dict[str, Any] | None]  # HTTP method -> request body


ENDPOINTS: list[Endpoint] = [
    Endpoint(
        "org-detail",
        kwargs=("org",),
        methods={"GET": None, "PATCH": {"name": "Renamed by intruder"}},
    ),
    Endpoint(
        "site-list",
        kwargs=("org",),
        methods={"GET": None, "POST": {"name": "Intruder site", "slug": "intruder"}},
    ),
    Endpoint(
        "site-detail",
        kwargs=("org", "site_id"),
        methods={
            "GET": None,
            "PATCH": {"name": "Renamed by intruder", "timezone": "UTC"},
            "DELETE": None,
        },
    ),
    Endpoint("member-list", kwargs=("org",), methods={"GET": None}),
    Endpoint(
        "member-detail",
        kwargs=("org", "membership_id"),
        methods={"PATCH": {"org_role": "admin"}, "DELETE": None},
    ),
    Endpoint(
        "member-site-role",
        kwargs=("org", "membership_id", "site_id"),
        methods={"PUT": {"role": "event_staff"}, "DELETE": None},
    ),
    Endpoint("audit-log", kwargs=("org",), methods={"GET": None}),
]

# Routes under /api/manage/ that are not tenant-scoped, with the reason.
EXEMPT: dict[str, str] = {
    "me": "User-scoped: returns only the caller's own memberships, no org in the URL.",
}


# Two identical tenants


@dataclass
class Tenant:
    label: str
    org: Organization
    sites: dict[str, Site] = field(default_factory=dict)
    members: dict[str, Membership] = field(default_factory=dict)

    def url_kwargs(self) -> dict[str, Any]:
        return {
            "org": self.org.slug,
            "site_id": self.sites["main"].id,
            "membership_id": self.members["editor"].id,
        }

    def markers(self) -> list[str]:
        """Strings that must never appear in a response to another tenant."""
        values = [self.org.name, self.org.slug, str(self.org.id)]
        for site in self.sites.values():
            values += [site.name, str(site.id)]
        for membership in self.members.values():
            values += [str(membership.id), str(membership.user.id), membership.user.email]
        return values

    def snapshot(self) -> dict[str, Any]:
        org = self.org
        return {
            "org": list(Organization.objects.filter(id=org.id).values()),
            "sites": list(Site.objects.for_org(org).order_by("id").values()),
            "members": list(Membership.objects.for_org(org).order_by("id").values()),
            "site_roles": list(SiteRole.objects.for_org(org).order_by("id").values()),
            "audit": AuditLog.objects.for_org(org).count(),
        }


def build_tenant(label: str) -> Tenant:
    org = OrganizationFactory(name=f"Tenant {label} Org", slug=f"tenant-{label}")
    tenant = Tenant(label=label, org=org)
    for slug in ("main", "events"):
        tenant.sites[slug] = SiteFactory(organization=org, slug=slug, name=f"Tenant {label} {slug}")
    for role in (Role.OWNER, Role.ADMIN, Role.EDITOR):
        tenant.members[role.value] = MembershipFactory(
            organization=org, org_role=role, user=UserFactory(email=f"{role}-{label}@example.com")
        )
    site_only = MembershipFactory(
        organization=org, org_role=None, user=UserFactory(email=f"site-only-{label}@example.com")
    )
    SiteRoleFactory(membership=site_only, site=tenant.sites["main"], role=Role.EDITOR)
    SiteRoleFactory(membership=site_only, site=tenant.sites["events"], role=Role.EVENT_STAFF)
    tenant.members["site_only"] = site_only
    return tenant


@dataclass
class World:
    a: Tenant
    b: Tenant


@pytest.fixture
def world(db) -> World:
    return World(a=build_tenant("a"), b=build_tenant("b"))


# Cases


@dataclass(frozen=True)
class Case:
    endpoint: Endpoint
    method: str
    # "b-org": all of B's kwargs. "a-org-b-ids": A's slug with all of B's object IDs.
    # "a-org-b-<kwarg>": A's slug and A's IDs, except <kwarg> taken from B.
    variant: str
    actor: str

    def __str__(self) -> str:
        return f"{self.endpoint.name}:{self.method}:{self.variant}:{self.actor}"

    def url(self, world: World) -> str:
        a, b = world.a.url_kwargs(), world.b.url_kwargs()
        if self.variant == "b-org":
            kwargs = {key: b[key] for key in self.endpoint.kwargs}
        elif self.variant == "a-org-b-ids":
            kwargs = {key: a[key] if key == "org" else b[key] for key in self.endpoint.kwargs}
        else:
            foreign = self.variant.removeprefix("a-org-b-")
            kwargs = {key: b[key] if key == foreign else a[key] for key in self.endpoint.kwargs}
        return reverse(self.endpoint.name, kwargs=kwargs)


def _variants(endpoint: Endpoint) -> list[str]:
    object_ids = [key for key in endpoint.kwargs if key != "org"]
    variants = ["b-org"]
    if object_ids:
        variants.append("a-org-b-ids")
    if len(object_ids) > 1:
        variants += [f"a-org-b-{key}" for key in object_ids]
    return variants


CASES = [
    Case(endpoint, method, variant, actor)
    for endpoint in ENDPOINTS
    for method in endpoint.methods
    for variant in _variants(endpoint)
    for actor in ACTORS
]

CONTROLS = [(endpoint, method) for endpoint in ENDPOINTS for method in endpoint.methods]


def _send(browser, method: str, url: str, body: dict | None):
    return browser.send(method.lower(), url, body)


# Isolation


@pytest.mark.parametrize("case", CASES, ids=str)
def test_cross_tenant_request_is_404(case: Case, world: World, browser):
    browser.force_login(world.a.members[case.actor].user)
    before = (world.a.snapshot(), world.b.snapshot())

    response = _send(browser, case.method, case.url(world), case.endpoint.methods[case.method])

    assert response.status_code == 404, response.content
    assert response.json() == NOT_FOUND
    body = response.content.decode()
    leaked = [marker for marker in world.b.markers() if marker in body]
    assert not leaked
    assert (world.a.snapshot(), world.b.snapshot()) == before


@pytest.mark.parametrize(
    ("endpoint", "method"), CONTROLS, ids=[f"{e.name}:{m}" for e, m in CONTROLS]
)
def test_same_tenant_control_is_not_404(endpoint: Endpoint, method: str, world: World, browser):
    """Proves each registered URL and body really reach the view, so the 404s above mean it."""
    browser.force_login(world.a.members["owner"].user)
    kwargs = {key: world.a.url_kwargs()[key] for key in endpoint.kwargs}

    response = _send(
        browser, method, reverse(endpoint.name, kwargs=kwargs), endpoint.methods[method]
    )

    assert response.status_code != 404, response.content
    assert response.status_code < 500


# Coverage: every /api/manage/ route is registered


def _manage_routes() -> dict[str | None, URLPattern]:
    routes: dict[str | None, URLPattern] = {}

    def walk(patterns, prefix: str) -> None:
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, route)
            elif route.startswith(MANAGE_PREFIX):
                assert pattern.name, f"Unnamed management route {route!r}"
                routes[pattern.name] = pattern

    walk(get_resolver().url_patterns, "")
    return routes


def _view_methods(pattern: URLPattern) -> set[str]:
    view = getattr(pattern.callback, "view_class", None) or pattern.callback.cls
    return {method.upper() for method in HTTP_METHODS if hasattr(view, method)}


def test_every_manage_route_is_registered():
    routes = set(_manage_routes())
    registered = {endpoint.name for endpoint in ENDPOINTS}

    assert routes - registered - set(EXEMPT) == set(), "Register these in ENDPOINTS"
    assert (registered | set(EXEMPT)) - routes == set(), "Stale entries: no such route"
    assert not registered & set(EXEMPT)


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.name)
def test_registered_methods_match_the_view(endpoint: Endpoint):
    assert set(endpoint.methods) == _view_methods(_manage_routes()[endpoint.name])


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.name)
def test_registered_kwargs_match_the_route(endpoint: Endpoint):
    pattern = _manage_routes()[endpoint.name]

    assert set(endpoint.kwargs) == set(pattern.pattern.converters)
    assert "org" in endpoint.kwargs


def test_world_tenants_are_identical(world: World):
    def shape(tenant: Tenant):
        return (
            sorted(tenant.sites),
            sorted((key, m.org_role) for key, m in tenant.members.items()),
            sorted(
                (sr.site.slug, sr.role)
                for sr in SiteRole.objects.for_org(tenant.org).select_related("site")
            ),
        )

    assert shape(world.a) == shape(world.b)
