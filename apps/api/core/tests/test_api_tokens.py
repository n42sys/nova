import hashlib
import re
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.audit import audit
from core.context import ActorType, RequestContext
from core.models import ApiToken, AuditLog, Organization, Role, Site
from core.selectors.token_resolution import resolve_api_token
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
)
from core.tokens import hash_token, new_api_token, parse_api_token

pytestmark = pytest.mark.django_db

DELIVERY_SITE = "/api/v1/site/"


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def site(org):
    return SiteFactory(organization=org, slug="main", name="Main", timezone="Africa/Nairobi")


@pytest.fixture
def owner(org):
    return MembershipFactory(organization=org, org_role=Role.OWNER)


def _list_url(site):
    return reverse("api-token-list", kwargs={"org": site.organization.slug, "site_id": site.id})


def _detail_url(token):
    return reverse(
        "api-token-detail",
        kwargs={"org": token.organization.slug, "site_id": token.site_id, "token_id": token.id},
    )


def _create(browser, member, site, kind="delivery", name="Website") -> tuple[ApiToken, str]:
    browser.force_login(member.user)
    response = browser.send("post", _list_url(site), {"name": name, "kind": kind})
    assert response.status_code == 201, response.content
    browser.logout()
    raw = response.json()["token"]
    return ApiToken.objects.for_org(site.organization).get(id=response.json()["id"]), raw


def _bearer(client, raw, path=DELIVERY_SITE, **extra):
    return client.get(path, HTTP_AUTHORIZATION=f"Bearer {raw}", **extra)


# Format


@pytest.mark.parametrize(("kind", "tag"), [("delivery", "dlv"), ("preview", "prv")])
def test_token_format(kind, tag):
    raw, prefix, secret_hash = new_api_token(kind)

    match = re.fullmatch(rf"nova_{tag}_([a-z0-9]{{8}})_([A-Za-z0-9]{{43}})", raw)
    assert match and match.group(1) == prefix
    secret = match.group(2)
    assert secret_hash == hashlib.sha256(secret.encode()).hexdigest() == hash_token(secret)
    parsed = parse_api_token(raw)
    assert (parsed.kind, parsed.prefix, parsed.secret) == (kind, prefix, secret)
    assert new_api_token(kind)[0] != raw


# Management endpoints


def test_create_returns_raw_token_once(browser, owner, site):
    token, raw = _create(browser, owner, site)

    assert raw.startswith(f"nova_dlv_{token.prefix}_")
    assert token.token_hash == hash_token(raw.rsplit("_", 1)[1])
    secret = raw.rsplit("_", 1)[1]
    browser.force_login(owner.user)
    listed = browser.get(_list_url(site))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(token.id)]
    assert "token" not in listed.json()[0] and "token_hash" not in listed.json()[0]
    for text in (
        listed.content.decode(),
        str(list(ApiToken.objects.for_org(site.organization).values())),
        str(list(AuditLog.objects.for_org(site.organization).values())),
    ):
        assert secret not in text
    entry = AuditLog.objects.for_org(site.organization).get(action="api_token.create")
    assert entry.metadata == {
        "name": "Website",
        "kind": "delivery",
        "prefix": token.prefix,
        "site_id": str(site.id),
    }


def test_preview_token(browser, owner, site):
    token, raw = _create(browser, owner, site, kind="preview")

    assert raw.startswith("nova_prv_")
    assert token.kind == ApiToken.Kind.PREVIEW


@pytest.mark.parametrize("org_role", [Role.EDITOR, Role.EVENT_STAFF])
def test_editors_cannot_manage_tokens(browser, org, site, org_role):
    browser.force_login(MembershipFactory(organization=org, org_role=org_role).user)

    assert browser.get(_list_url(site)).status_code == 403
    assert (
        browser.send("post", _list_url(site), {"name": "x", "kind": "delivery"}).status_code == 403
    )


def test_site_admin_manages_tokens_only_for_their_site(browser, org, site):
    other = SiteFactory(organization=org, slug="events")
    site_admin = SiteRoleFactory(
        membership__organization=org, membership__org_role=None, site=site, role=Role.ADMIN
    ).membership
    browser.force_login(site_admin.user)

    assert (
        browser.send("post", _list_url(site), {"name": "x", "kind": "delivery"}).status_code == 201
    )
    assert (
        browser.send("post", _list_url(other), {"name": "x", "kind": "delivery"}).status_code == 404
    )


def test_revoke_is_immediate_and_idempotent(browser, client, owner, site):
    token, raw = _create(browser, owner, site)
    assert _bearer(client, raw).status_code == 200
    browser.force_login(owner.user)

    assert browser.send("delete", _detail_url(token)).status_code == 204
    assert browser.send("delete", _detail_url(token)).status_code == 204
    assert _bearer(client, raw).status_code == 401
    assert (
        AuditLog.objects.for_org(site.organization).filter(action="api_token.revoke").count() == 1
    )


def test_invalid_create_body_is_400(browser, owner, site):
    browser.force_login(owner.user)

    assert browser.send("post", _list_url(site), {"name": "x", "kind": "admin"}).status_code == 400
    assert browser.send("post", _list_url(site), {"kind": "delivery"}).status_code == 400


# Bearer authentication


def test_valid_token_reads_its_site(browser, client, owner, site):
    _, raw = _create(browser, owner, site)

    response = _bearer(client, raw)

    assert response.status_code == 200
    assert response.json() == {
        "name": "Main",
        "slug": "main",
        "timezone": "Africa/Nairobi",
        "locale": "en",
    }


def _assert_401(response):
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'
    assert response.json()["error"]["code"] in {"authentication_failed", "not_authenticated"}


def test_revoked_token_is_401(browser, client, owner, site):
    token, raw = _create(browser, owner, site)
    ApiToken.objects.for_org(site.organization).filter(id=token.id).update(
        revoked_at=timezone.now()
    )

    _assert_401(_bearer(client, raw))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "nova",
        "nova_dlv_",
        "nova_dlv_abcdefgh_short",
        "nova_xyz_abcdefgh_" + "a" * 43,
        "nova_dlv_ABCDEFGH_" + "a" * 43,  # prefix must be lowercase
        "nova_dlv_abcdefgh_" + "a" * 42 + "!",
        "x" * 5000,
    ],
)
def test_malformed_tokens_are_401(client, raw):
    _assert_401(_bearer(client, raw))


def test_wrong_kind_prefix_is_401(browser, client, owner, site):
    _, raw = _create(browser, owner, site, kind="delivery")

    _assert_401(_bearer(client, raw.replace("nova_dlv_", "nova_prv_", 1)))


def test_wrong_secret_and_unknown_prefix_are_401(browser, client, owner, site):
    token, raw = _create(browser, owner, site)
    head, secret = raw.rsplit("_", 1)
    other_secret = ("B" if secret[0] != "B" else "C") + secret[1:]

    _assert_401(_bearer(client, f"{head}_{other_secret}"))
    _assert_401(
        _bearer(
            client,
            raw.replace(token.prefix, "zzzzzzzz" if token.prefix != "zzzzzzzz" else "yyyyyyyy"),
        )
    )


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "Bearer ", "Basic Zm9vOmJhcg=="])
def test_bad_authorization_headers_are_401(client, header):
    _assert_401(client.get(DELIVERY_SITE, HTTP_AUTHORIZATION=header))


def test_missing_token_is_401(client):
    _assert_401(client.get(DELIVERY_SITE))


def test_archived_site_and_suspended_org_tokens_are_401(browser, client, owner, site):
    _, raw = _create(browser, owner, site)

    Site.objects.for_org(site.organization).filter(id=site.id).update(status=Site.Status.ARCHIVED)
    _assert_401(_bearer(client, raw))
    Site.objects.for_org(site.organization).filter(id=site.id).update(status=Site.Status.ACTIVE)
    assert _bearer(client, raw).status_code == 200
    Organization.objects.filter(id=site.organization_id).update(
        status=Organization.Status.SUSPENDED
    )
    _assert_401(_bearer(client, raw))


# Two auth worlds


@pytest.mark.parametrize("path_name", ["me", "org-detail", "site-list"])
def test_delivery_token_cannot_call_management(browser, client, owner, site, path_name):
    _, raw = _create(browser, owner, site)
    kwargs = {} if path_name == "me" else {"org": site.organization.slug}

    response = _bearer(client, raw, path=reverse(path_name, kwargs=kwargs))

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Session realm="api"'


def test_session_cannot_call_delivery(browser, owner, site):
    browser.force_login(owner.user)

    response = browser.get(DELIVERY_SITE)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'


# Site scoping


def test_token_for_site_a_only_sees_site_a(browser, client, owner, site):
    events = SiteFactory(organization=site.organization, slug="events", name="Events")
    other_org_site = SiteFactory(organization=OrganizationFactory(), slug="main", name="Elsewhere")
    _, raw_main = _create(browser, owner, site)
    _, raw_events = _create(browser, owner, events)
    _, raw_other = _create(
        browser,
        MembershipFactory(organization=other_org_site.organization, org_role=Role.OWNER),
        other_org_site,
    )

    assert _bearer(client, raw_main).json()["name"] == "Main"
    assert _bearer(client, raw_events).json()["name"] == "Events"
    assert _bearer(client, raw_other).json()["name"] == "Elsewhere"
    resolved = resolve_api_token(raw_main)
    assert (resolved.site_id, resolved.organization_id) == (site.id, site.organization_id)


# last_used_at and throttling


def test_last_used_at_is_written_at_most_once_a_minute(browser, client, owner, site):
    token, raw = _create(browser, owner, site)
    assert token.last_used_at is None

    _bearer(client, raw)
    token.refresh_from_db()
    first = token.last_used_at
    assert first is not None

    ApiToken.objects.for_org(site.organization).filter(id=token.id).update(
        last_used_at=first - timedelta(minutes=5)
    )
    _bearer(client, raw)  # within the minute: no write
    token.refresh_from_db()
    assert token.last_used_at == first - timedelta(minutes=5)

    cache.delete(f"api-token-used:{token.id}")  # the minute has passed
    _bearer(client, raw)
    token.refresh_from_db()
    assert token.last_used_at > first - timedelta(minutes=5)


@override_settings(NOVA_API_TOKEN_RATE="2/min")
def test_rate_limit_is_per_token(browser, client, owner, site):
    _, raw_a = _create(browser, owner, site, name="A")
    _, raw_b = _create(browser, owner, site, name="B")

    assert [_bearer(client, raw_a).status_code for _ in range(3)] == [200, 200, 429]
    throttled = _bearer(client, raw_a)
    assert throttled.json()["error"]["code"] == "throttled"
    assert _bearer(client, raw_b).status_code == 200


# Audit attribution


def test_token_actor_is_recorded_in_audit(site):
    token = ApiToken.unscoped.create(
        organization=site.organization,
        site=site,
        name="x",
        kind=ApiToken.Kind.DELIVERY,
        prefix="abcdefgh",
        token_hash="0" * 64,
    )
    ctx = RequestContext(
        user=None,
        membership=None,
        organization=site.organization,
        ip=None,
        actor_type=ActorType.TOKEN,
        api_token_id=token.id,
    )

    entry = audit(ctx, "delivery.test", site)

    assert (entry.actor_user, entry.actor_token_id) == (None, token.id)


# Every failure looks the same


def test_every_token_failure_returns_an_identical_401(browser, client, owner, site):
    token, raw = _create(browser, owner, site)
    revoked, revoked_raw = _create(browser, owner, site, name="Revoked")
    ApiToken.objects.for_org(site.organization).filter(id=revoked.id).update(
        revoked_at=timezone.now()
    )
    archived_site = SiteFactory(organization=site.organization, slug="old")
    _, archived_raw = _create(browser, owner, archived_site)
    Site.objects.for_org(site.organization).filter(id=archived_site.id).update(
        status=Site.Status.ARCHIVED
    )
    suspended_site = SiteFactory(organization=OrganizationFactory())
    _, suspended_raw = _create(
        browser,
        MembershipFactory(organization=suspended_site.organization, org_role=Role.OWNER),
        suspended_site,
    )
    Organization.objects.filter(id=suspended_site.organization_id).update(
        status=Organization.Status.SUSPENDED
    )
    head, secret = raw.rsplit("_", 1)
    unknown_prefix = "zzzzzzzz" if token.prefix != "zzzzzzzz" else "yyyyyyyy"

    failures = {
        "malformed": "Bearer nova_dlv_nope",
        "unknown prefix": f"Bearer {raw.replace(token.prefix, unknown_prefix)}",
        "wrong secret": f"Bearer {head}_{('B' if secret[0] != 'B' else 'C') + secret[1:]}",
        "wrong kind": f"Bearer {raw.replace('nova_dlv_', 'nova_prv_', 1)}",
        "revoked": f"Bearer {revoked_raw}",
        "archived site": f"Bearer {archived_raw}",
        "suspended org": f"Bearer {suspended_raw}",
        "wrong scheme": f"Token {raw}",
        "empty bearer": "Bearer ",
    }
    responses = {
        name: client.get(DELIVERY_SITE, HTTP_AUTHORIZATION=header)
        for name, header in failures.items()
    }

    assert {name: r.status_code for name, r in responses.items()} == dict.fromkeys(failures, 401)
    bodies = {r.content for r in responses.values()}
    headers = {r["WWW-Authenticate"] for r in responses.values()}
    assert bodies == {
        b'{"error":{"code":"authentication_failed","message":"Invalid API token.","details":null}}'
    }
    assert headers == {'Bearer realm="api"'}
    assert _bearer(client, raw).status_code == 200  # the control token still works


def test_suspended_org_token_is_401(browser, client, owner, site):
    _, raw = _create(browser, owner, site)
    assert _bearer(client, raw).status_code == 200

    Organization.objects.filter(id=site.organization_id).update(
        status=Organization.Status.SUSPENDED
    )

    _assert_401(_bearer(client, raw))


def test_prefix_has_a_unique_index():
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, ApiToken._meta.db_table)

    assert any(info["columns"] == ["prefix"] and info["unique"] for info in constraints.values())
