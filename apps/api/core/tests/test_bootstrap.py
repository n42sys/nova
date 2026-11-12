import io
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Invitation, Membership, Organization, Role, Site
from core.selectors.memberships import get_membership
from core.tests.factories import MembershipFactory, UserFactory
from core.tests.support import PASSWORD

pytestmark = pytest.mark.django_db

ARGS = [
    "--name",
    "Culture & Interest",
    "--slug",
    "culture-interest",
    "--owner-email",
    "Owner@Culture.example",
    "--site",
    "Main:main",
]


def _run(*args: str) -> str:
    out = io.StringIO()
    with TestCase.captureOnCommitCallbacks(execute=True):  # invitation emails go out on commit
        call_command("bootstrap_org", *args, stdout=out)
    return out.getvalue()


def _org() -> Organization:
    return Organization.objects.get(slug="culture-interest")


def _snapshot() -> dict:
    org = _org()
    return {
        "orgs": Organization.objects.count(),
        "org": Organization.objects.filter(id=org.id).values("name", "features", "status").get(),
        "sites": sorted(Site.objects.for_org(org).values_list("slug", flat=True)),
        "invitations": list(
            Invitation.objects.for_org(org).values("id", "token_hash", "revoked_at")
        ),
        "memberships": Membership.objects.for_org(org).count(),
        "audit": AuditLog.objects.for_org(org).count(),
        "emails": len(mail.outbox),
    }


def test_creates_org_site_features_and_owner_invitation(settings):
    output = _run(*ARGS)

    org = _org()
    assert org.name == "Culture & Interest"
    assert org.features == {"forms": True, "events": True, "content": True}
    assert [(s.name, s.slug) for s in Site.objects.for_org(org)] == [("Main", "main")]
    invitation = Invitation.objects.for_org(org).get()
    assert (invitation.email, invitation.org_role, invitation.site_roles) == (
        "owner@culture.example",
        Role.OWNER,
        [],
    )
    assert invitation.invited_by is None
    assert mail.outbox[-1].to == ["owner@culture.example"]
    assert f"{settings.NOVA_ADMIN_URL}/invite/" in mail.outbox[-1].body
    assert "Created organization Culture & Interest" in output
    assert "Owner invitation emailed to owner@culture.example." in output
    actions = set(AuditLog.objects.for_org(org).values_list("action", flat=True))
    assert actions == {"org.bootstrap", "site.create", "invitation.create"}
    assert not AuditLog.objects.for_org(org).exclude(actor_user=None).exists()  # system actor


def test_rerunning_duplicates_nothing():
    _run(*ARGS)
    before = _snapshot()

    output = _run(*ARGS)

    assert _snapshot() == before
    assert "already exists" in output
    assert "Sites already present: main." in output
    assert "still open; none sent" in output


def test_resend_sends_a_fresh_link_without_a_new_invitation():
    _run(*ARGS)
    first = Invitation.objects.for_org(_org()).get()

    output = _run(*ARGS, "--resend")

    second = Invitation.objects.for_org(_org()).get()
    assert second.id == first.id and second.token_hash != first.token_hash
    assert len(mail.outbox) == 2
    assert "fresh owner invitation link" in output


def test_no_invitation_once_the_owner_is_a_member():
    _run(*ARGS)
    user = UserFactory(email="owner@culture.example")
    MembershipFactory(organization=_org(), user=user, org_role=Role.OWNER)
    before = _snapshot()

    output = _run(*ARGS, "--resend")

    assert _snapshot() == before
    assert "already an owner" in output


def test_expired_invitation_is_replaced():
    _run(*ARGS)
    Invitation.objects.for_org(_org()).update(expires_at=timezone.now() - timedelta(minutes=1))

    _run(*ARGS)

    invitations = Invitation.objects.for_org(_org())
    assert invitations.count() == 2
    assert [i.status for i in invitations.order_by("created_at")] == ["revoked", "open"]


def test_adds_new_sites_and_features_but_keeps_existing_ones():
    _run(*ARGS)
    org = _org()
    Site.objects.for_org(org).filter(slug="main").update(name="Main stage")

    output = _run(
        "--name",
        "Renamed?",
        "--slug",
        "culture-interest",
        "--owner-email",
        "owner@culture.example",
        "--site",
        "Main:main",
        "--site",
        "Screenings:screenings",
        "--features",
        "forms,events,content,tickets",
    )

    org.refresh_from_db()
    assert org.name == "Culture & Interest"
    assert org.features == {"forms": True, "events": True, "content": True, "tickets": True}
    sites = dict(Site.objects.for_org(org).values_list("slug", "name"))
    assert sites == {"main": "Main stage", "screenings": "Screenings"}
    assert "--name was ignored" in output
    assert "Turned on features: tickets." in output
    assert "Created sites: screenings." in output


@pytest.mark.parametrize(
    "args",
    [
        ["--name", "X", "--slug", "Not A Slug", "--owner-email", "a@b.co", "--site", "Main:main"],
        ["--name", "X", "--slug", "x", "--owner-email", "not-an-email", "--site", "Main:main"],
        ["--name", "X", "--slug", "x", "--owner-email", "a@b.co", "--site", "no-colon"],
        ["--name", "X", "--slug", "x", "--owner-email", "a@b.co", "--site", "Main:bad slug"],
        ["--name", "X", "--slug", "x", "--owner-email", "a@b.co", "--site", ":main"],
        ["--name", "X", "--slug", "x", "--owner-email", "a@b.co", "--site", "A:a", "--site", "B:a"],
        ["--name", " ", "--slug", "x", "--owner-email", "a@b.co", "--site", "Main:main"],
        [
            "--name",
            "X",
            "--slug",
            "x",
            "--owner-email",
            "a@b.co",
            "--site",
            "M:m",
            "--features",
            "Bad-Flag",
        ],
    ],
)
def test_invalid_arguments_change_nothing(args):
    with pytest.raises(CommandError):
        _run(*args)

    assert not Organization.objects.exists()
    assert mail.outbox == []


def test_owner_accepts_and_completes_setup(browser):
    """Acceptance: the owner receives the invite, accepts, and can set the org up."""
    _run(*ARGS)
    token = re.search(r"/invite/(\S+)", mail.outbox[-1].body).group(1)

    assert browser.get(f"/api/manage/invitations/{token}/").json()["org_role"] == "owner"
    assert browser.send("post", f"/api/manage/invitations/{token}/claim/").status_code == 204
    signup = browser.send(
        "post",
        "/_allauth/browser/v1/auth/signup",
        {"email": "owner@culture.example", "password": PASSWORD},
    )
    assert signup.status_code == 200
    assert browser.send("post", f"/api/manage/invitations/{token}/accept/").status_code == 200

    org = _org()
    owner = get_membership(org, Membership.objects.for_org(org).get().user)
    assert owner.org_role == Role.OWNER
    me = browser.get("/api/manage/me/").json()["organizations"][0]
    assert {"payments.manage", "members.manage", "sites.manage"} <= set(me["permissions"])
    # setup through the admin's API: a second site and a first team member
    site_list = reverse("site-list", kwargs={"org": org.slug})
    created = browser.send("post", site_list, {"name": "Screenings", "slug": "screenings"})
    assert created.status_code == 201
    with TestCase.captureOnCommitCallbacks(execute=True):
        invite = browser.send(
            "post",
            reverse("invitation-list", kwargs={"org": org.slug}),
            {"email": "editor@culture.example", "org_role": "editor"},
        )
    assert invite.status_code == 201
    assert len(mail.outbox) == 2
