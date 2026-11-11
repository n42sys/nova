import pytest
from django.urls import reverse

from core.audit import audit
from core.context import ActorType, RequestContext
from core.models import Role
from core.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return MembershipFactory(org_role=Role.ADMIN)


def _url(org, **params):
    url = reverse("audit-log", kwargs={"org": org.slug})
    return url + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")


def _entries(membership, count):
    ctx = RequestContext(
        user=membership.user,
        membership=membership,
        organization=membership.organization,
        ip="203.0.113.7",
        actor_type=ActorType.USER,
    )
    return [audit(ctx, f"test.{i}", None, {"n": i}) for i in range(count)]


def test_admin_reads_entries_newest_first(browser, admin):
    entries = _entries(admin, 2)
    browser.force_login(admin.user)

    response = browser.get(_url(admin.organization))

    assert response.status_code == 200
    body = response.json()
    assert [entry["id"] for entry in body["results"]] == [str(e.id) for e in reversed(entries)]
    assert body["next_cursor"] is None
    first = body["results"][0]
    assert first["action"] == "test.1"
    assert first["actor_user"] == {
        "id": str(admin.user.id),
        "email": admin.user.email,
        "name": admin.user.name,
    }
    assert (first["metadata"], first["ip"], first["actor_token_id"]) == (
        {"n": 1},
        "203.0.113.7",
        None,
    )


def test_pagination_with_cursor(browser, admin):
    _entries(admin, 5)
    browser.force_login(admin.user)

    first = browser.get(_url(admin.organization, limit=3)).json()
    second = browser.get(_url(admin.organization, limit=3, cursor=first["next_cursor"])).json()

    assert len(first["results"]) == 3 and len(second["results"]) == 2
    assert second["next_cursor"] is None
    ids = [e["id"] for e in first["results"] + second["results"]]
    assert len(set(ids)) == 5


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"limit": "x"}, {"cursor": "junk"}]
)
def test_bad_query_params_are_400(browser, admin, params):
    browser.force_login(admin.user)

    response = browser.get(_url(admin.organization, **params))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize("org_role", [Role.EDITOR, Role.EVENT_STAFF])
def test_audit_view_needs_owner_or_admin(browser, admin, org_role):
    member = MembershipFactory(organization=admin.organization, org_role=org_role)
    browser.force_login(member.user)

    assert browser.get(_url(admin.organization)).status_code == 403
