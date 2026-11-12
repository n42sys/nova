import hashlib
import re
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from core.auth_adapter import AccountAdapter
from core.context import ActorType, RequestContext
from core.invitation_session import SESSION_KEY, remember_invitation
from core.models import AuditLog, Invitation, Organization, Role, Site, SiteRole, User
from core.selectors.memberships import get_membership
from core.selectors.token_resolution import resolve_invitation_token
from core.services.invitations import invite_member
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
    UserFactory,
)
from core.tests.support import PASSWORD
from core.tokens import hash_token, is_well_formed_invitation_token, new_invitation_token

pytestmark = pytest.mark.django_db

AUTH = "/_allauth/browser/v1"


@pytest.fixture
def org():
    return OrganizationFactory(name="Culture & Interest")


@pytest.fixture
def owner(org):
    return MembershipFactory(organization=org, org_role=Role.OWNER)


@pytest.fixture
def admin(org):
    return MembershipFactory(organization=org, org_role=Role.ADMIN)


@pytest.fixture
def site(org):
    return SiteFactory(organization=org, slug="main", name="Main")


def _ctx(membership) -> RequestContext:
    loaded = get_membership(membership.organization, membership.user)
    return RequestContext(
        user=loaded.user,
        membership=loaded,
        organization=loaded.organization,
        ip=None,
        actor_type=ActorType.USER,
    )


def _token_from_outbox() -> str:
    match = re.search(r"/invite/(\S+)", mail.outbox[-1].body)
    assert match, mail.outbox[-1].body
    return match.group(1)


def _invite(membership, django_capture_on_commit_callbacks, **kwargs) -> tuple[Invitation, str]:
    kwargs.setdefault("email", "new.person@example.com")
    kwargs.setdefault("org_role", Role.EDITOR)
    with django_capture_on_commit_callbacks(execute=True):
        invitation = invite_member(_ctx(membership), **kwargs)
    return invitation, _token_from_outbox()


def _list_url(org):
    return reverse("invitation-list", kwargs={"org": org.slug})


def _preview_url(token):
    return reverse("invitation-preview", kwargs={"token": token})


def _claim(browser, token):
    return browser.send("post", reverse("invitation-claim", kwargs={"token": token}))


def _accept(browser, token):
    return browser.send("post", reverse("invitation-accept", kwargs={"token": token}))


# Tokens


def test_token_is_32_random_urlsafe_bytes_and_only_its_hash_is_kept():
    token, token_hash = new_invitation_token()

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)  # 32 bytes, URL-safe base64
    assert "." not in token  # no org id or other structure
    assert token_hash == hashlib.sha256(token.encode()).hexdigest() == hash_token(token)
    assert new_invitation_token()[0] != token


@pytest.mark.parametrize("token", ["", "abc", "A" * 42, "A" * 44, "A" * 42 + "!", "x" * 5000])
def test_malformed_tokens_are_rejected_before_lookup(token):
    assert not is_well_formed_invitation_token(token)
    assert resolve_invitation_token(token) is None


def test_resolution_returns_invitation_with_its_organization(
    owner, django_capture_on_commit_callbacks, django_assert_num_queries
):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)

    with django_assert_num_queries(1):
        resolved = resolve_invitation_token(token)
        assert resolved == invitation
        assert resolved.organization == owner.organization


def test_raw_token_never_stored_or_returned(browser, owner, django_capture_on_commit_callbacks):
    browser.force_login(owner.user)
    with django_capture_on_commit_callbacks(execute=True):
        response = browser.send(
            "post", _list_url(owner.organization), {"email": "a@example.com", "org_role": "editor"}
        )
    token = _token_from_outbox()
    invitation = Invitation.objects.for_org(owner.organization).get()
    secret = token

    with django_capture_on_commit_callbacks(execute=True):
        resent = browser.send(
            "post",
            reverse(
                "invitation-resend",
                kwargs={"org": owner.organization.slug, "invitation_id": invitation.id},
            ),
        )
    new_secret = _token_from_outbox()

    for raw in (secret, new_secret):
        assert raw not in response.content.decode() and raw not in resent.content.decode()
        assert raw not in str(list(Invitation.objects.for_org(owner.organization).values()))
        assert raw not in str(list(AuditLog.objects.for_org(owner.organization).values()))


# Create


def test_invite_creates_open_invitation_and_emails_link(
    owner, site, settings, django_capture_on_commit_callbacks
):
    invitation, token = _invite(
        owner,
        django_capture_on_commit_callbacks,
        email="  New.Person@Example.com ",
        org_role=None,
        site_roles=[{"site_id": site.id, "role": Role.EVENT_STAFF}],
    )

    assert invitation.email == "new.person@example.com"
    assert invitation.site_roles == [{"site_id": str(site.id), "role": "event_staff"}]
    assert invitation.status == Invitation.Status.OPEN
    assert invitation.invited_by == owner.user
    assert timedelta(days=6, hours=23) < invitation.expires_at - timezone.now() <= timedelta(days=7)
    assert invitation.token_hash == hash_token(token)
    assert mail.outbox[-1].to == ["new.person@example.com"]
    assert f"{settings.NOVA_ADMIN_URL}/invite/{token}" in mail.outbox[-1].body
    assert "Culture & Interest" in mail.outbox[-1].subject
    entry = AuditLog.objects.for_org(owner.organization).get(action="invitation.create")
    assert entry.metadata == {
        "email": "new.person@example.com",
        "org_role": None,
        "site_roles": [{"site_id": str(site.id), "role": "event_staff"}],
    }


def test_no_email_when_the_transaction_rolls_back(owner, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        invite_member(_ctx(owner), email="x@example.com", org_role=Role.EDITOR)

    assert len(callbacks) == 1
    assert mail.outbox == []  # sent only by the on_commit callback


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"org_role": "editor"}, 201),
        ({"org_role": "event_staff"}, 201),
        ({"site_roles": [{"role": "editor"}]}, 201),
        ({"site_roles": [{"role": "event_staff"}]}, 201),
        ({"org_role": "admin"}, 403),
        ({"org_role": "owner"}, 403),
        ({"site_roles": [{"role": "admin"}]}, 403),
        ({"org_role": "editor", "site_roles": [{"role": "admin"}]}, 403),
    ],
)
def test_admins_invite_only_below_admin(browser, admin, site, body, expected):
    for item in body.get("site_roles", []):
        item["site_id"] = str(site.id)
    browser.force_login(admin.user)

    response = browser.send(
        "post", _list_url(admin.organization), {"email": "x@example.com", **body}
    )

    assert response.status_code == expected
    assert Invitation.objects.for_org(admin.organization).exists() == (expected == 201)


@pytest.mark.parametrize(
    "body",
    [
        {"org_role": "owner"},
        {"org_role": "admin"},
        {"site_roles": [{"role": "admin"}]},
    ],
)
def test_owners_invite_owner_and_admin(browser, owner, site, body):
    for item in body.get("site_roles", []):
        item["site_id"] = str(site.id)
    browser.force_login(owner.user)

    response = browser.send(
        "post", _list_url(owner.organization), {"email": "x@example.com", **body}
    )

    assert response.status_code == 201


@pytest.mark.parametrize("org_role", [Role.EDITOR, Role.EVENT_STAFF])
def test_non_managers_cannot_invite(browser, org, org_role):
    member = MembershipFactory(organization=org, org_role=org_role)
    browser.force_login(member.user)

    response = browser.send(
        "post", _list_url(org), {"email": "x@example.com", "org_role": "editor"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"org_role": None, "site_roles": []},
        {"org_role": "owner", "site_roles": [{"role": "editor"}]},
        {"site_roles": [{"role": "owner"}]},
        {"site_roles": [{"role": "editor"}, {"role": "event_staff"}]},  # same site twice
        {"site_roles": [{"site_id": "foreign", "role": "editor"}]},
        {"site_roles": [{"site_id": "archived", "role": "editor"}]},
        {"site_roles": [{"site_id": str(uuid.uuid4()), "role": "editor"}]},
        {"org_role": "editor", "email": "not-an-email"},
    ],
)
def test_invalid_invitations_are_400(browser, owner, site, body):
    foreign = SiteFactory(organization=OrganizationFactory())
    archived = SiteFactory(organization=owner.organization, status=Site.Status.ARCHIVED)
    for item in body.get("site_roles", []):
        item["site_id"] = {"foreign": str(foreign.id), "archived": str(archived.id)}.get(
            item.get("site_id"), item.get("site_id", str(site.id))
        )
    browser.force_login(owner.user)

    response = browser.send(
        "post", _list_url(owner.organization), {"email": "x@example.com", **body}
    )

    assert response.status_code == 400, response.content
    assert not Invitation.objects.for_org(owner.organization).exists()


def test_foreign_site_id_is_indistinguishable_from_unknown(browser, owner):
    foreign = SiteFactory(organization=OrganizationFactory(), name="Other Tenant Site")
    browser.force_login(owner.user)

    def attempt(site_id):
        body = {"email": "x@example.com", "site_roles": [{"site_id": site_id, "role": "editor"}]}
        response = browser.send("post", _list_url(owner.organization), body)
        return response.status_code, response.json()["error"]["message"]

    assert attempt(str(foreign.id)) == attempt(str(uuid.uuid4())) == (400, "Unknown site.")


def test_reinviting_revokes_the_open_invitation(owner, django_capture_on_commit_callbacks, browser):
    first, first_token = _invite(owner, django_capture_on_commit_callbacks)
    second, second_token = _invite(
        owner, django_capture_on_commit_callbacks, org_role=Role.EVENT_STAFF
    )

    first.refresh_from_db()
    assert first.status == Invitation.Status.REVOKED
    assert second.status == Invitation.Status.OPEN
    assert browser.get(_preview_url(first_token)).status_code == 410
    assert browser.get(_preview_url(second_token)).status_code == 200
    revoke = AuditLog.objects.for_org(owner.organization).get(action="invitation.revoke")
    assert (revoke.target_id, revoke.metadata["reason"]) == (str(first.id), "reinvited")


# Revoke, resend, list


def test_revoke(browser, owner, django_capture_on_commit_callbacks):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)
    browser.force_login(owner.user)
    url = reverse(
        "invitation-detail", kwargs={"org": owner.organization.slug, "invitation_id": invitation.id}
    )

    assert browser.send("delete", url).status_code == 204
    assert browser.send("delete", url).status_code == 204  # idempotent
    assert (
        AuditLog.objects.for_org(owner.organization).filter(action="invitation.revoke").count() == 1
    )
    assert browser.get(_preview_url(token)).status_code == 410


def test_accepted_invitation_cannot_be_revoked_or_resent(
    browser, owner, django_capture_on_commit_callbacks
):
    invitation, _ = _invite(owner, django_capture_on_commit_callbacks)
    Invitation.objects.for_org(owner.organization).filter(id=invitation.id).update(
        accepted_at=timezone.now()
    )
    browser.force_login(owner.user)
    kwargs = {"org": owner.organization.slug, "invitation_id": invitation.id}

    assert browser.send("delete", reverse("invitation-detail", kwargs=kwargs)).status_code == 409
    assert browser.send("post", reverse("invitation-resend", kwargs=kwargs)).status_code == 409


def test_admin_cannot_revoke_or_resend_an_admin_invitation(
    browser, owner, admin, django_capture_on_commit_callbacks
):
    invitation, _ = _invite(owner, django_capture_on_commit_callbacks, org_role=Role.ADMIN)
    browser.force_login(admin.user)
    kwargs = {"org": owner.organization.slug, "invitation_id": invitation.id}

    assert browser.send("delete", reverse("invitation-detail", kwargs=kwargs)).status_code == 403
    assert browser.send("post", reverse("invitation-resend", kwargs=kwargs)).status_code == 403


def test_resend_rotates_token_and_restarts_expiry(
    browser, owner, django_capture_on_commit_callbacks
):
    invitation, old_token = _invite(owner, django_capture_on_commit_callbacks)
    Invitation.objects.for_org(owner.organization).filter(id=invitation.id).update(
        expires_at=timezone.now() + timedelta(hours=1)
    )
    browser.force_login(owner.user)
    url = reverse(
        "invitation-resend", kwargs={"org": owner.organization.slug, "invitation_id": invitation.id}
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = browser.send("post", url)
    new_token = _token_from_outbox()

    assert response.status_code == 200
    assert new_token != old_token
    invitation.refresh_from_db()
    assert invitation.expires_at - timezone.now() > timedelta(days=6)
    assert browser.get(_preview_url(old_token)).status_code == 404
    assert browser.get(_preview_url(new_token)).status_code == 200


def test_list_invitations(browser, owner, admin, django_capture_on_commit_callbacks):
    invitation, _ = _invite(owner, django_capture_on_commit_callbacks)
    browser.force_login(admin.user)

    response = browser.get(_list_url(owner.organization))

    assert response.status_code == 200
    [item] = response.json()
    assert item["id"] == str(invitation.id)
    assert item["status"] == "open"
    assert item["invited_by"]["email"] == owner.user.email
    assert "token" not in str(item).lower()


def test_editors_cannot_list_invitations(browser, org):
    editor = MembershipFactory(organization=org, org_role=Role.EDITOR)
    browser.force_login(editor.user)

    assert browser.get(_list_url(org)).status_code == 403


# Public preview


def test_preview_shows_invitation_and_is_read_only(
    browser, owner, site, django_capture_on_commit_callbacks
):
    invitation, token = _invite(
        owner,
        django_capture_on_commit_callbacks,
        org_role=None,
        site_roles=[{"site_id": site.id, "role": Role.EDITOR}],
    )

    response = browser.get(_preview_url(token))

    assert response.status_code == 200
    assert response.json() == {
        "organization": {"name": "Culture & Interest", "slug": owner.organization.slug},
        "email": "new.person@example.com",
        "invited_by_name": owner.user.name,
        "org_role": None,
        "site_roles": [{"site_id": str(site.id), "site_name": "Main", "role": "editor"}],
        "expires_at": response.json()["expires_at"],
        "account_exists": False,
    }
    assert SESSION_KEY not in browser.session  # GET never writes the session
    assert _signup_open(browser) is False


def test_claim_remembers_invitation_in_session(browser, owner, django_capture_on_commit_callbacks):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)

    response = _claim(browser, token)

    assert response.status_code == 204
    assert browser.session[SESSION_KEY] == {
        "org_id": str(owner.organization_id),
        "invitation_id": str(invitation.id),
    }


def test_claim_requires_csrf(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks)

    response = browser.post(reverse("invitation-claim", kwargs={"token": token}))

    assert response.status_code == 403
    assert SESSION_KEY not in browser.session


@pytest.mark.parametrize("token", ["A" * 43, "nope"])
def test_claim_of_unknown_token_is_404(browser, token):
    assert _claim(browser, token).status_code == 404


def test_preview_reports_existing_account(browser, owner, django_capture_on_commit_callbacks):
    UserFactory(email="new.person@example.com")
    _, token = _invite(owner, django_capture_on_commit_callbacks)

    assert browser.get(_preview_url(token)).json()["account_exists"] is True


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"expires_at": timezone.now() - timedelta(seconds=1)}, "expired"),
        ({"revoked_at": timezone.now()}, "revoked"),
        ({"accepted_at": timezone.now()}, "accepted"),
    ],
)
def test_dead_invitations_are_410(
    browser, owner, django_capture_on_commit_callbacks, change, status
):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)
    Invitation.objects.for_org(owner.organization).filter(id=invitation.id).update(**change)

    response = browser.get(_preview_url(token))

    assert response.status_code == 410
    assert _claim(browser, token).status_code == 410
    assert response.json()["error"] == {
        "code": "gone",
        "message": f"This invitation has {status}.",
        "details": {"status": status},
    }
    assert SESSION_KEY not in browser.session


def test_unknown_and_malformed_tokens_are_404(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks)

    for bad in ("nope", "A" * 43, token[:-1] + ("A" if token[-1] != "A" else "B")):
        response = browser.get(_preview_url(bad))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_suspended_org_invitation_is_404(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks)
    Organization.objects.filter(id=owner.organization_id).update(
        status=Organization.Status.SUSPENDED
    )

    assert browser.get(_preview_url(token)).status_code == 404


# Sign-up adapter


def _signup(browser, email, password=PASSWORD):
    return browser.send("post", f"{AUTH}/auth/signup", {"email": email, "password": password})


def _signup_open(browser) -> bool:
    return browser.get(f"{AUTH}/config").json()["data"]["account"]["is_open_for_signup"]


def test_signup_is_closed_without_an_opened_invitation(
    browser, owner, django_capture_on_commit_callbacks
):
    _invite(owner, django_capture_on_commit_callbacks)  # exists, but this browser never opened it

    assert _signup_open(browser) is False
    assert _signup(browser, "new.person@example.com").status_code == 403
    assert not User.objects.filter(email="new.person@example.com").exists()


def test_signup_with_the_invited_email_is_verified_and_logged_in(
    browser, owner, django_capture_on_commit_callbacks
):
    _, token = _invite(owner, django_capture_on_commit_callbacks)
    _claim(browser, token)
    assert _signup_open(browser) is True

    response = _signup(browser, "New.Person@example.com")

    assert response.status_code == 200, response.content
    assert response.json()["meta"]["is_authenticated"] is True
    user = User.objects.get(email="new.person@example.com")
    assert EmailAddress.objects.get(user=user).verified is True
    assert browser.get("/api/manage/me/").json()["email"] == "new.person@example.com"


def test_signup_with_another_email_is_rejected(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks)
    _claim(browser, token)

    response = _signup(browser, "someone.else@example.com")

    assert response.status_code == 400
    assert not User.objects.filter(email="someone.else@example.com").exists()


@pytest.mark.parametrize(
    "change",
    [{"revoked_at": timezone.now()}, {"expires_at": timezone.now() - timedelta(seconds=1)}],
)
def test_signup_closes_if_the_invitation_dies_after_preview(
    browser, owner, django_capture_on_commit_callbacks, change
):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)
    _claim(browser, token)
    Invitation.objects.for_org(owner.organization).filter(id=invitation.id).update(**change)

    assert _signup_open(browser) is False
    assert _signup(browser, "new.person@example.com").status_code == 403


def test_invite_for_a_cannot_be_used_to_sign_up_b(
    browser, owner, django_capture_on_commit_callbacks
):
    _, token = _invite(owner, django_capture_on_commit_callbacks, email="a@x.com")
    _claim(browser, token)

    response = _signup(browser, "b@x.com")

    assert response.status_code == 400
    assert not User.objects.filter(email="b@x.com").exists()
    assert not EmailAddress.objects.filter(email__iexact="b@x.com").exists()
    assert browser.get("/api/manage/me/").status_code == 401


@pytest.mark.parametrize("signup_email", ["a@x.com", "A@X.com", "  a@X.COM "])
def test_signup_marks_verified_only_the_invitations_normalised_email(
    browser, owner, django_capture_on_commit_callbacks, signup_email
):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks, email="  A@x.com ")
    assert invitation.email == "a@x.com"
    _claim(browser, token)

    response = _signup(browser, signup_email)

    assert response.status_code == 200, response.content
    address = EmailAddress.objects.get(user__email="a@x.com")
    assert (address.email.lower(), address.verified) == ("a@x.com", True)


def test_adapter_never_verifies_another_email(rf, owner, django_capture_on_commit_callbacks):
    invitation, _ = _invite(owner, django_capture_on_commit_callbacks, email="a@x.com")
    request = rf.post("/")
    request.session = SessionStore()
    adapter = AccountAdapter(request)

    assert adapter.is_email_verified(request, "a@x.com") is False  # nothing claimed yet
    remember_invitation(request, invitation)
    assert adapter.is_email_verified(request, "A@X.com") is True
    assert adapter.is_email_verified(request, "b@x.com") is False


# Accept


def _login_as(browser, email):
    user = User.objects.filter(email=email).first() or UserFactory(email=email)
    EmailAddress.objects.get_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    browser.force_login(user)
    return user


def test_accept_creates_membership_with_site_roles(
    browser, owner, site, django_capture_on_commit_callbacks
):
    events = SiteFactory(organization=owner.organization, slug="events", name="Events")
    invitation, token = _invite(
        owner,
        django_capture_on_commit_callbacks,
        org_role=None,
        site_roles=[
            {"site_id": site.id, "role": Role.EDITOR},
            {"site_id": events.id, "role": Role.EVENT_STAFF},
        ],
    )
    user = _login_as(browser, "new.person@example.com")

    response = _accept(browser, token)

    assert response.status_code == 200, response.content
    assert response.json()["slug"] == owner.organization.slug
    membership = get_membership(owner.organization, user)
    assert membership.org_role is None
    assert membership.effective_role(site) == Role.EDITOR
    assert membership.effective_role(events) == Role.EVENT_STAFF
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED
    entry = AuditLog.objects.for_org(owner.organization).get(action="invitation.accept")
    assert (entry.actor_user, entry.target_id) == (user, str(invitation.id))
    assert entry.metadata["membership_created"] is True
    assert browser.get("/api/manage/me/").json()["organizations"][0]["site_roles"]


def test_accept_with_org_role(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks, org_role=Role.ADMIN)
    user = _login_as(browser, "new.person@example.com")

    assert _accept(browser, token).status_code == 200
    assert get_membership(owner.organization, user).org_role == Role.ADMIN


def test_accept_merges_into_existing_membership_without_downgrading(
    browser, owner, site, django_capture_on_commit_callbacks
):
    events = SiteFactory(organization=owner.organization, slug="events")
    shop = SiteFactory(organization=owner.organization, slug="shop")
    user = _login_as(browser, "new.person@example.com")
    existing = MembershipFactory(
        organization=owner.organization, user=user, org_role=Role.EVENT_STAFF
    )
    SiteRoleFactory(membership=existing, site=site, role=Role.ADMIN)
    _, token = _invite(
        owner,
        django_capture_on_commit_callbacks,
        org_role=Role.EDITOR,
        site_roles=[
            {"site_id": site.id, "role": Role.EDITOR},  # lower than existing admin: ignored
            {"site_id": events.id, "role": Role.ADMIN},  # higher than editor: applied
        ],
    )

    assert _accept(browser, token).status_code == 200

    membership = get_membership(owner.organization, user)
    assert membership.id == existing.id
    assert membership.org_role == Role.EDITOR  # raised from event_staff
    assert membership.effective_role(site) == Role.ADMIN
    assert membership.effective_role(events) == Role.ADMIN
    assert membership.effective_role(shop) == Role.EDITOR


def test_accept_never_lowers_org_role(browser, owner, django_capture_on_commit_callbacks):
    user = _login_as(browser, "new.person@example.com")
    MembershipFactory(organization=owner.organization, user=user, org_role=Role.ADMIN)
    _, token = _invite(owner, django_capture_on_commit_callbacks, org_role=Role.EVENT_STAFF)

    assert _accept(browser, token).status_code == 200
    assert get_membership(owner.organization, user).org_role == Role.ADMIN


def test_raised_org_role_drops_lower_site_roles(
    browser, owner, site, django_capture_on_commit_callbacks
):
    user = _login_as(browser, "new.person@example.com")
    existing = MembershipFactory(organization=owner.organization, user=user, org_role=None)
    SiteRoleFactory(membership=existing, site=site, role=Role.EVENT_STAFF)
    _, token = _invite(owner, django_capture_on_commit_callbacks, org_role=Role.EDITOR)

    assert _accept(browser, token).status_code == 200
    assert get_membership(owner.organization, user).effective_role(site) == Role.EDITOR


def test_accepting_owner_removes_site_roles(
    browser, owner, site, django_capture_on_commit_callbacks
):
    user = _login_as(browser, "new.person@example.com")
    existing = MembershipFactory(organization=owner.organization, user=user, org_role=None)
    SiteRoleFactory(membership=existing, site=site, role=Role.ADMIN)
    _, token = _invite(owner, django_capture_on_commit_callbacks, org_role=Role.OWNER)

    assert _accept(browser, token).status_code == 200
    membership = get_membership(owner.organization, user)
    assert membership.org_role == Role.OWNER
    assert not SiteRole.objects.for_org(owner.organization).filter(membership=membership).exists()


def test_accept_marks_existing_unverified_email_verified(
    browser, owner, django_capture_on_commit_callbacks
):
    user = UserFactory(email="new.person@example.com")
    EmailAddress.objects.create(user=user, email=user.email, verified=False, primary=True)
    browser.force_login(user)
    _, token = _invite(owner, django_capture_on_commit_callbacks)

    assert _accept(browser, token).status_code == 200
    assert EmailAddress.objects.get(user=user).verified is True


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"expires_at": timezone.now() - timedelta(seconds=1)}, "expired"),
        ({"revoked_at": timezone.now()}, "revoked"),
        ({"accepted_at": timezone.now()}, "accepted"),
    ],
)
def test_accept_fails_cleanly_for_dead_invitations(
    browser, owner, django_capture_on_commit_callbacks, change, status
):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)
    Invitation.objects.for_org(owner.organization).filter(id=invitation.id).update(**change)
    user = _login_as(browser, "new.person@example.com")

    response = _accept(browser, token)

    assert response.status_code == 410
    assert response.json()["error"]["details"] == {"status": status}
    assert get_membership(owner.organization, user) is None


def test_accept_twice_fails_the_second_time(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks)
    _login_as(browser, "new.person@example.com")

    assert _accept(browser, token).status_code == 200
    assert _accept(browser, token).status_code == 410
    assert (
        AuditLog.objects.for_org(owner.organization).filter(action="invitation.accept").count() == 1
    )


def test_accept_with_wrong_email_fails_cleanly(browser, owner, django_capture_on_commit_callbacks):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)
    user = _login_as(browser, "someone.else@example.com")

    response = _accept(browser, token)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert get_membership(owner.organization, user) is None
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.OPEN


def test_accept_requires_login(browser, owner, django_capture_on_commit_callbacks):
    _, token = _invite(owner, django_capture_on_commit_callbacks)

    assert _accept(browser, token).status_code == 401


def test_accept_unknown_token_is_404(browser):
    _login_as(browser, "new.person@example.com")

    assert _accept(browser, "A" * 43).status_code == 404


def test_failed_audit_rolls_back_accept(browser, owner, django_capture_on_commit_callbacks):
    invitation, token = _invite(owner, django_capture_on_commit_callbacks)
    user = _login_as(browser, "new.person@example.com")

    with (
        mock.patch("core.services.invitations.audit", side_effect=RuntimeError("audit down")),
        pytest.raises(RuntimeError),
    ):
        _accept(browser, token)

    assert get_membership(owner.organization, user) is None
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.OPEN


def test_full_new_user_flow(browser, owner, site, django_capture_on_commit_callbacks):
    """Open link -> claim -> sign up (verified, logged in) -> accept -> member."""
    _, token = _invite(
        owner,
        django_capture_on_commit_callbacks,
        email="newbie@example.com",
        org_role=None,
        site_roles=[{"site_id": site.id, "role": Role.EDITOR}],
    )

    assert browser.get(_preview_url(token)).json()["account_exists"] is False
    assert _claim(browser, token).status_code == 204
    assert _signup(browser, "newbie@example.com").status_code == 200
    assert _accept(browser, token).status_code == 200

    orgs = browser.get("/api/manage/me/").json()["organizations"]
    assert [(o["slug"], o["site_roles"][0]["role"]) for o in orgs] == [
        (owner.organization.slug, "editor")
    ]
    assert SESSION_KEY not in browser.session
