"""Tenant isolation suite.

Two organizations, A and B, hold identical data. Every management endpoint is called by a
member of A against B: with B's org slug; with A's slug but B's object IDs; and, for URLs
with several IDs, with A's slug and A's IDs except one taken from B. Each call must return
the standard 404 body, contain no B data and change nothing in A or B.

Every route under /api/manage/ must be registered in ENDPOINTS (or EXEMPT, with a reason);
the coverage tests fail otherwise, including when a view gains an unregistered method.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from core import storage
from core.models import (
    ApiToken,
    AuditLog,
    Invitation,
    MediaAsset,
    Membership,
    Organization,
    Role,
    Site,
    SiteRole,
)
from core.tests.factories import (
    InvitationFactory,
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
    UserFactory,
)
from core.tokens import new_api_token, new_invitation_token
from payments.models import PaymentAccount
from payments.providers import PROVIDERS
from payments.tests.factories import PaymentAccountFactory

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
    # HTTP method -> request body: a dict, None, or a callable building it from a Tenant
    # (for bodies that carry tenant IDs; those also get an "a-org-b-body" variant).
    methods: dict[str, dict[str, Any] | Callable[[Tenant], dict[str, Any]] | None]

    def body(self, method: str, tenant: Tenant) -> dict[str, Any] | None:
        body = self.methods[method]
        return body(tenant) if callable(body) else body


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
    Endpoint(
        "api-token-list",
        kwargs=("org", "site_id"),
        methods={"GET": None, "POST": {"name": "Intruder", "kind": "delivery"}},
    ),
    Endpoint("api-token-detail", kwargs=("org", "site_id", "token_id"), methods={"DELETE": None}),
    Endpoint(
        "media-upload",
        kwargs=("org",),
        methods={
            "POST": lambda t: {
                "filename": "intruder.png",
                "mime_type": "image/png",
                "size_bytes": 10,
                "site_id": str(t.sites["main"].id),
            }
        },
    ),
    Endpoint(
        "media-list",
        kwargs=("org",),
        methods={"GET": None, "POST": lambda t: {"asset_id": str(t.pending_asset.id)}},
    ),
    Endpoint(
        "media-detail",
        kwargs=("org", "asset_id"),
        methods={"PATCH": {"alt_text": "Renamed by intruder"}, "DELETE": None},
    ),
    Endpoint(
        "payment-account-list",
        kwargs=("org",),
        methods={
            "GET": None,
            "POST": {
                "provider": "paystack",
                "public_key": "pk_test_" + "c" * 32,
                "secret_key": "sk_test_" + "d" * 32,
            },
        },
    ),
    Endpoint(
        "payment-account-detail",
        kwargs=("org", "account_id"),
        methods={
            "PATCH": {"public_key": "pk_test_" + "e" * 32, "secret_key": "sk_test_" + "f" * 32},
            "DELETE": None,
        },
    ),
    Endpoint("payment-account-verify", kwargs=("org", "account_id"), methods={"POST": None}),
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
    Endpoint(
        "invitation-list",
        kwargs=("org",),
        methods={"GET": None, "POST": {"email": "intruder@example.com", "org_role": "editor"}},
    ),
    Endpoint("invitation-detail", kwargs=("org", "invitation_id"), methods={"DELETE": None}),
    Endpoint("invitation-resend", kwargs=("org", "invitation_id"), methods={"POST": None}),
]

# Token-scoped routes: no org in the URL; the raw token is the credential. Called by a member
# of A with a random token and with B's dead (revoked) token, they must reveal nothing about B
# and change nothing. Valid-token behaviour is tested in test_invitations.py.
TOKEN_ENDPOINTS: dict[str, str] = {
    "invitation-preview": "GET",
    "invitation-claim": "POST",
    "invitation-accept": "POST",
}

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
    invitation: Invitation | None = None
    revoked_invitation_token: str = ""
    api_token: ApiToken | None = None
    asset: MediaAsset | None = None  # ready, with its R2 object
    pending_asset: MediaAsset | None = None  # uploaded but not yet confirmed
    payment_account: PaymentAccount | None = None

    def url_kwargs(self) -> dict[str, Any]:
        return {
            "org": self.org.slug,
            "site_id": self.sites["main"].id,
            "membership_id": self.members["editor"].id,
            "invitation_id": self.invitation.id,
            "token_id": self.api_token.id,
            "asset_id": self.asset.id,
            "account_id": self.payment_account.id,
        }

    def markers(self) -> list[str]:
        """Strings that must never appear in a response to another tenant."""
        values = [self.org.name, self.org.slug, str(self.org.id)]
        for site in self.sites.values():
            values += [site.name, str(site.id)]
        for membership in self.members.values():
            values += [str(membership.id), str(membership.user.id), membership.user.email]
        values += [str(self.invitation.id), self.invitation.email]
        values += [str(self.api_token.id), self.api_token.name, self.api_token.prefix]
        for asset in (self.asset, self.pending_asset):
            values += [str(asset.id), asset.file_key]
        values.append(self.asset.alt_text)
        account = self.payment_account
        values += [str(account.id), account.public_key, account.secret_key_hint]
        return values

    def snapshot(self) -> dict[str, Any]:
        org = self.org
        return {
            "org": list(Organization.objects.filter(id=org.id).values()),
            "sites": list(Site.objects.for_org(org).order_by("id").values()),
            "members": list(Membership.objects.for_org(org).order_by("id").values()),
            "site_roles": list(SiteRole.objects.for_org(org).order_by("id").values()),
            "invitations": list(Invitation.objects.for_org(org).order_by("id").values()),
            "api_tokens": list(ApiToken.objects.for_org(org).order_by("id").values()),
            "media": list(MediaAsset.objects.for_org(org).order_by("id").values()),
            "payment_accounts": list(PaymentAccount.objects.for_org(org).order_by("id").values()),
            "r2_objects": sorted(
                item["Key"]
                for item in storage._client()
                .list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=f"orgs/{org.id}/")
                .get("Contents", [])
            ),
            "audit": AuditLog.objects.for_org(org).count(),
        }


def _media(tenant: Tenant, s3, *, status: str, name: str, alt_text: str = "") -> MediaAsset:
    asset = MediaAsset.unscoped.create(
        organization=tenant.org,
        site=tenant.sites["main"],
        file_key=f"orgs/{tenant.org.id}/{tenant.label}-{name}/{name}.png",
        mime_type="image/png",
        size_bytes=4,
        alt_text=alt_text,
        status=status,
        uploaded_by=tenant.members["editor"].user,
    )
    s3.put_object(
        Bucket=settings.R2_BUCKET, Key=asset.file_key, Body=b"\x89PNG", ContentType="image/png"
    )
    return asset


def build_tenant(label: str, s3) -> Tenant:
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
    tenant.invitation = InvitationFactory(
        organization=org,
        email=f"invitee-{label}@example.com",
        org_role=None,
        site_roles=[{"site_id": str(tenant.sites["events"].id), "role": "event_staff"}],
        invited_by=tenant.members["owner"].user,
    )
    token, token_hash = new_invitation_token()
    InvitationFactory(
        organization=org,
        email=f"revoked-{label}@example.com",
        token_hash=token_hash,
        revoked_at=timezone.now(),
        invited_by=tenant.members["owner"].user,
    )
    tenant.revoked_invitation_token = token
    _, prefix, token_hash = new_api_token("delivery")
    tenant.api_token = ApiToken.unscoped.create(
        organization=org,
        site=tenant.sites["main"],
        name=f"Tenant {label} website",
        kind=ApiToken.Kind.DELIVERY,
        prefix=prefix,
        token_hash=token_hash,
    )
    tenant.asset = _media(
        tenant, s3, status=MediaAsset.Status.READY, name="poster", alt_text=f"Tenant {label} poster"
    )
    tenant.pending_asset = _media(tenant, s3, status=MediaAsset.Status.PENDING, name="flyer")
    tenant.payment_account = PaymentAccountFactory(
        organization=org,
        public_key=f"pk_test_tenant{label}" + "p" * 24,
        secret_key=f"sk_test_tenant{label}" + "s" * 24,
    )
    return tenant


@dataclass
class World:
    a: Tenant
    b: Tenant


class _AcceptingProvider:
    """Stands in for Paystack so the suite never makes a network call."""

    def verify_credentials(self, account: PaymentAccount) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_network_payments(monkeypatch):
    monkeypatch.setitem(PROVIDERS, PaymentAccount.Provider.PAYSTACK, _AcceptingProvider())


@pytest.fixture
def world(db, s3) -> World:
    return World(a=build_tenant("a", s3), b=build_tenant("b", s3))


# Cases


@dataclass(frozen=True)
class Case:
    endpoint: Endpoint
    method: str
    # "b-org": all of B's kwargs. "a-org-b-ids": A's slug with all of B's object IDs.
    # "a-org-b-<kwarg>": A's slug and A's IDs, except <kwarg> taken from B.
    # "a-org-b-body": A's URL, with B's IDs in the request body.
    variant: str
    actor: str

    def __str__(self) -> str:
        return f"{self.endpoint.name}:{self.method}:{self.variant}:{self.actor}"

    def body(self, world: World) -> dict[str, Any] | None:
        tenant = world.b if self.variant in {"b-org", "a-org-b-body"} else world.a
        return self.endpoint.body(self.method, tenant)

    def url(self, world: World) -> str:
        a, b = world.a.url_kwargs(), world.b.url_kwargs()
        if self.variant == "a-org-b-body":
            kwargs = {key: a[key] for key in self.endpoint.kwargs}
        elif self.variant == "b-org":
            kwargs = {key: b[key] for key in self.endpoint.kwargs}
        elif self.variant == "a-org-b-ids":
            kwargs = {key: a[key] if key == "org" else b[key] for key in self.endpoint.kwargs}
        else:
            foreign = self.variant.removeprefix("a-org-b-")
            kwargs = {key: b[key] if key == foreign else a[key] for key in self.endpoint.kwargs}
        return reverse(self.endpoint.name, kwargs=kwargs)


def _variants(endpoint: Endpoint, method: str) -> list[str]:
    object_ids = [key for key in endpoint.kwargs if key != "org"]
    variants = ["b-org"]
    if object_ids:
        variants.append("a-org-b-ids")
    if len(object_ids) > 1:
        variants += [f"a-org-b-{key}" for key in object_ids]
    if callable(endpoint.methods[method]):
        variants.append("a-org-b-body")
    return variants


CASES = [
    Case(endpoint, method, variant, actor)
    for endpoint in ENDPOINTS
    for method in endpoint.methods
    for variant in _variants(endpoint, method)
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

    response = _send(browser, case.method, case.url(world), case.body(world))

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
        browser, method, reverse(endpoint.name, kwargs=kwargs), endpoint.body(method, world.a)
    )

    assert response.status_code != 404, response.content
    assert response.status_code < 500


# Coverage: every /api/manage/ route is registered


@dataclass(frozen=True)
class Route:
    pattern: URLPattern
    kwargs: frozenset[str]  # URL kwargs from the whole path, including include() prefixes


def _manage_routes() -> dict[str, Route]:
    routes: dict[str, Route] = {}

    def walk(patterns, prefix: str, kwargs: frozenset[str]) -> None:
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            route_kwargs = kwargs | set(pattern.pattern.converters)
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, route, route_kwargs)
            elif route.startswith(MANAGE_PREFIX):
                assert pattern.name, f"Unnamed management route {route!r}"
                routes[pattern.name] = Route(pattern=pattern, kwargs=route_kwargs)

    walk(get_resolver().url_patterns, "", frozenset())
    return routes


def _view_methods(route: Route) -> set[str]:
    view = getattr(route.pattern.callback, "view_class", None) or route.pattern.callback.cls
    return {method.upper() for method in HTTP_METHODS if hasattr(view, method)}


def test_every_manage_route_is_registered():
    routes = set(_manage_routes())
    registered = {endpoint.name for endpoint in ENDPOINTS}
    listed = registered | set(TOKEN_ENDPOINTS) | set(EXEMPT)

    assert routes - listed == set(), "Register these in ENDPOINTS or TOKEN_ENDPOINTS"
    assert listed - routes == set(), "Stale entries: no such route"
    assert len(listed) == len(registered) + len(TOKEN_ENDPOINTS) + len(EXEMPT)


@pytest.mark.parametrize("name", sorted(TOKEN_ENDPOINTS))
def test_token_endpoint_methods_match_the_view(name):
    assert _view_methods(_manage_routes()[name]) == {TOKEN_ENDPOINTS[name]}


TOKEN_CASES = [
    (name, token_kind, actor)
    for name in sorted(TOKEN_ENDPOINTS)
    for token_kind in ("random", "b-revoked")
    for actor in ACTORS
]


@pytest.mark.parametrize(
    ("name", "token_kind", "actor"), TOKEN_CASES, ids=[":".join(case) for case in TOKEN_CASES]
)
def test_token_route_reveals_nothing_without_a_valid_token(name, token_kind, actor, world, browser):
    browser.force_login(world.a.members[actor].user)
    token = "A" * 43 if token_kind == "random" else world.b.revoked_invitation_token
    before = (world.a.snapshot(), world.b.snapshot())

    response = _send(browser, TOKEN_ENDPOINTS[name], reverse(name, kwargs={"token": token}), None)

    if token_kind == "random":
        assert response.status_code == 404
        assert response.json() == NOT_FOUND
    else:
        assert response.status_code == 410
        assert response.json()["error"]["details"] == {"status": "revoked"}
    body = response.content.decode()
    assert [marker for marker in world.b.markers() if marker in body] == []
    assert (world.a.snapshot(), world.b.snapshot()) == before


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.name)
def test_registered_methods_match_the_view(endpoint: Endpoint):
    assert set(endpoint.methods) == _view_methods(_manage_routes()[endpoint.name])


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.name)
def test_registered_kwargs_match_the_route(endpoint: Endpoint):
    route = _manage_routes()[endpoint.name]

    assert set(endpoint.kwargs) == route.kwargs
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
