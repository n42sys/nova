import io
import json
import logging

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.db import connection
from django.urls import reverse

from core import crypto
from core.exceptions import ProviderUnavailable
from core.models import AuditLog, Role
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
)
from payments.api.serializers import PaymentAccountSerializer
from payments.models import PaymentAccount
from payments.providers import PROVIDERS
from payments.providers.base import CredentialsRejected
from payments.services import secret_hint
from payments.tests.factories import TEST_SECRET, PaymentAccountFactory

pytestmark = pytest.mark.django_db

PUBLIC = "pk_live_" + "Pub1" * 8
SECRET = "sk_live_" + "Zx9q" * 8 + "a1b2"


def _keys(public=PUBLIC, secret=SECRET):
    return {"public_key": public, "secret_key": secret}


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def owner(org):
    return MembershipFactory(organization=org, org_role=Role.OWNER)


def _list_url(org):
    return reverse("payment-account-list", kwargs={"org": org.slug})


def _detail_url(account):
    return reverse(
        "payment-account-detail",
        kwargs={"org": account.organization.slug, "account_id": account.id},
    )


def _verify_url(account):
    return reverse(
        "payment-account-verify",
        kwargs={"org": account.organization.slug, "account_id": account.id},
    )


class FakeProvider:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[PaymentAccount] = []

    def verify_credentials(self, account: PaymentAccount) -> None:
        self.calls.append(account)
        if self.error is not None:
            raise self.error


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setitem(PROVIDERS, PaymentAccount.Provider.PAYSTACK, fake)
    return fake


# Secret hygiene (acceptance)


def test_secret_hygiene(browser, client, org, owner, provider, caplog):
    """Raw payment secrets and API tokens never appear in responses, logs or audit metadata.

    The one deliberate exception is the API token creation response, which shows the raw
    token once; every other response, every log record (including SQL with parameters) and
    every audit entry is checked.
    """
    second_secret = "sk_live_" + "Qw3e" * 8 + "c3d4"
    rejected_secret = "sk_test_" + "Mm7n" * 8 + "e5f6"
    site = SiteFactory(organization=org)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="django")  # Django defaults its tree to INFO
    responses = []
    connection.force_debug_cursor = True  # log every SQL statement with its parameters
    try:
        browser.force_login(owner.user)
        created = browser.send("post", _list_url(org), {"provider": "paystack", **_keys()})
        assert created.status_code == 201, created.content
        responses.append(created)
        account = PaymentAccount.objects.for_org(org).get()
        responses += [
            browser.get(_list_url(org)),
            browser.send("post", _list_url(org), {"provider": "paystack", **_keys()}),  # 409
            browser.send(  # 400: test secret with a live public key
                "patch", _detail_url(account), _keys(secret=rejected_secret)
            ),
            browser.send("patch", _detail_url(account), _keys(secret=second_secret)),
        ]
        provider.error = CredentialsRejected(f"bad key {second_secret}")  # must not leak
        responses.append(browser.send("post", _verify_url(account)))
        provider.error = ProviderUnavailable(f"timeout using {second_secret}")
        responses.append(browser.send("post", _verify_url(account)))
        provider.error = None
        responses.append(browser.send("post", _verify_url(account)))

        token_created = browser.send(
            "post",
            reverse("api-token-list", kwargs={"org": org.slug, "site_id": site.id}),
            {"name": "Website", "kind": "delivery"},
        )
        assert token_created.status_code == 201
        raw_token = token_created.json()["token"]  # the one response allowed to carry it
        responses += [
            browser.get(reverse("api-token-list", kwargs={"org": org.slug, "site_id": site.id})),
            client.get("/api/v1/site/", HTTP_AUTHORIZATION=f"Bearer {raw_token}"),
            client.get("/api/v1/site/", HTTP_AUTHORIZATION=f"Bearer {raw_token[:-1]}X"),
            browser.get(reverse("audit-log", kwargs={"org": org.slug})),
            browser.get(reverse("org-detail", kwargs={"org": org.slug})),
            browser.get(reverse("me")),
            browser.send("delete", _detail_url(account)),
        ]
    finally:
        connection.force_debug_cursor = False

    raw_secrets = {
        "payment secret": SECRET,
        "second payment secret": second_secret,
        "rejected payment secret": rejected_secret,
        "api token": raw_token,
        "api token secret": raw_token.rsplit("_", 1)[1],
    }
    bodies = [response.content.decode() for response in responses]
    log_lines = [record.getMessage() for record in caplog.records]
    audit_metadata = [
        json.dumps(metadata)
        for metadata in AuditLog.objects.for_org(org).values_list("metadata", flat=True)
    ]
    assert any(r.name == "django.db.backends" for r in caplog.records)  # SQL was captured
    assert len(audit_metadata) >= 6
    for label, raw in raw_secrets.items():
        assert not [b for b in bodies if raw in b], f"{label} in a response body"
        assert not [line for line in log_lines if raw in line], f"{label} in a log record"
        assert not [m for m in audit_metadata if raw in m], f"{label} in audit metadata"

    stored = PaymentAccount.objects.for_org(org).get()
    assert second_secret.encode() not in bytes(stored.secret_key_encrypted)
    assert crypto.decrypt(stored.secret_key_encrypted) == second_secret
    assert created.json()["secret_key_hint"] == "sk_live_…a1b2"


# Owner only


@pytest.mark.parametrize("org_role", [Role.ADMIN, Role.EDITOR, Role.EVENT_STAFF, None])
def test_non_owners_get_403_on_every_endpoint(browser, org, org_role):
    account = PaymentAccountFactory(organization=org)
    if org_role is None:  # site-only member, even an admin of a site
        member = SiteRoleFactory(
            membership__organization=org, membership__org_role=None, role=Role.ADMIN
        ).membership
    else:
        member = MembershipFactory(organization=org, org_role=org_role)
    browser.force_login(member.user)

    calls = [
        browser.get(_list_url(org)),
        browser.send("post", _list_url(org), {"provider": "daraja", **_keys()}),
        browser.send("patch", _detail_url(account), _keys()),
        browser.send("post", _verify_url(account)),
        browser.send("delete", _detail_url(account)),
    ]

    assert [response.status_code for response in calls] == [403] * 5
    account.refresh_from_db()
    assert account.status == PaymentAccount.Status.PENDING
    assert not AuditLog.objects.for_org(org).exists()


def test_owner_of_another_org_gets_404_on_every_endpoint(browser, org):
    account = PaymentAccountFactory(organization=org)
    browser.force_login(MembershipFactory(org_role=Role.OWNER).user)

    calls = [
        browser.get(_list_url(org)),
        browser.send("post", _list_url(org), {"provider": "daraja", **_keys()}),
        browser.send("patch", _detail_url(account), _keys()),
        browser.send("post", _verify_url(account)),
        browser.send("delete", _detail_url(account)),
    ]

    assert [response.status_code for response in calls] == [404] * 5


# Behaviour


def test_create_and_list(browser, org, owner):
    browser.force_login(owner.user)

    response = browser.send("post", _list_url(org), {"provider": "paystack", **_keys()})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "provider",
        "public_key",
        "secret_key_hint",
        "status",
        "verified_at",
        "created_at",
        "updated_at",
    }
    assert (body["provider"], body["public_key"], body["status"], body["verified_at"]) == (
        "paystack",
        PUBLIC,
        "pending",
        None,
    )
    assert [item["id"] for item in browser.get(_list_url(org)).json()] == [body["id"]]


@pytest.mark.parametrize(
    "keys",
    [
        _keys(public="pk_live_short", secret=SECRET),
        _keys(public=PUBLIC, secret="sk_live_short"),
        _keys(public=PUBLIC, secret="pk_live_" + "x" * 32),
        _keys(public="pk_test_" + "x" * 32, secret=SECRET),  # test/live mismatch
        _keys(public=PUBLIC, secret="Zq81kX"),
    ],
)
def test_invalid_paystack_keys_are_400_without_echo(browser, org, owner, keys):
    browser.force_login(owner.user)

    response = browser.send("post", _list_url(org), {"provider": "paystack", **keys})

    assert response.status_code == 400
    assert keys["secret_key"] not in response.content.decode()
    assert not PaymentAccount.objects.for_org(org).exists()


def test_daraja_is_not_supported_yet(browser, org, owner):
    browser.force_login(owner.user)

    response = browser.send(
        "post",
        _list_url(org),
        {"provider": "daraja", "public_key": "consumer-key", "secret_key": "consumer-secret-xyz"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "This payment provider is not supported yet."
    assert not PaymentAccount.objects.for_org(org).exists()


def test_existing_daraja_account_keys_cannot_be_replaced(browser, org, owner):
    account = PaymentAccountFactory(organization=org, provider=PaymentAccount.Provider.DARAJA)
    browser.force_login(owner.user)

    response = browser.send("patch", _detail_url(account), {"public_key": "k", "secret_key": "s"})

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "This payment provider is not supported yet."


def test_serializer_exposes_only_the_hint():
    output = PaymentAccountSerializer()
    data = PaymentAccountSerializer(PaymentAccountFactory.build()).data

    assert (
        set(output.fields)
        == set(data)
        == {
            "id",
            "provider",
            "public_key",
            "secret_key_hint",
            "status",
            "verified_at",
            "created_at",
            "updated_at",
        }
    )
    assert [name for name in output.fields if "secret" in name] == ["secret_key_hint"]
    assert not [name for name, field in output.fields.items() if field.write_only]
    assert "secret_key_encrypted" not in data and "secret_key" not in data


def test_one_account_per_provider(browser, org, owner):
    PaymentAccountFactory(organization=org)
    browser.force_login(owner.user)

    response = browser.send("post", _list_url(org), {"provider": "paystack", **_keys()})

    assert response.status_code == 409


def test_replace_keys_resets_verification_and_reenables(browser, org, owner):
    account = PaymentAccountFactory(organization=org, status=PaymentAccount.Status.DISABLED)
    browser.force_login(owner.user)

    response = browser.send("patch", _detail_url(account), _keys())

    assert response.status_code == 200
    account.refresh_from_db()
    assert (account.status, account.verified_at, account.public_key) == ("pending", None, PUBLIC)
    assert crypto.decrypt(account.secret_key_encrypted) == SECRET
    entry = AuditLog.objects.for_org(org).get(action="payment_account.replace_keys")
    assert entry.metadata["key_hint"] == "sk_live_…a1b2"
    assert entry.metadata["previous_key_hint"] == secret_hint(TEST_SECRET)


def test_verify_success(browser, org, owner, provider):
    account = PaymentAccountFactory(organization=org)
    browser.force_login(owner.user)

    response = browser.send("post", _verify_url(account))

    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert response.json()["verified_at"] is not None
    assert [call.id for call in provider.calls] == [account.id]
    assert AuditLog.objects.for_org(org).filter(action="payment_account.verify").exists()


def test_verify_rejected_keys(browser, org, owner, provider):
    account = PaymentAccountFactory(organization=org, status=PaymentAccount.Status.VERIFIED)
    provider.error = CredentialsRejected("nope")
    browser.force_login(owner.user)

    response = browser.send("post", _verify_url(account))

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "The provider rejected these keys."
    account.refresh_from_db()
    assert (account.status, account.verified_at) == ("pending", None)
    assert AuditLog.objects.for_org(org).filter(action="payment_account.verify_failed").exists()


def test_verify_when_provider_unreachable_is_503_with_retry_after(browser, org, owner, provider):
    account = PaymentAccountFactory(organization=org, status=PaymentAccount.Status.VERIFIED)
    provider.error = ProviderUnavailable("timeout talking to provider")
    browser.force_login(owner.user)

    response = browser.send("post", _verify_url(account))

    assert response.status_code == 503
    assert response["Retry-After"] == "30"
    assert response.json() == {
        "error": {
            "code": "provider_unavailable",
            "message": "The provider could not be reached. Try again shortly.",
            "details": {"provider": "paystack"},
        }
    }
    account.refresh_from_db()
    assert account.status == PaymentAccount.Status.VERIFIED  # unchanged: nothing was learned
    assert not AuditLog.objects.for_org(org).exists()


def test_verify_unsupported_provider_or_disabled_account(browser, org, owner, provider):
    daraja = PaymentAccountFactory(
        organization=org, provider=PaymentAccount.Provider.DARAJA, public_key="consumer-key"
    )
    disabled = PaymentAccountFactory(organization=org, status=PaymentAccount.Status.DISABLED)
    browser.force_login(owner.user)

    assert browser.send("post", _verify_url(daraja)).status_code == 409
    assert browser.send("post", _verify_url(disabled)).status_code == 409
    assert provider.calls == []


def test_delete_disables_and_is_idempotent(browser, org, owner):
    account = PaymentAccountFactory(organization=org)
    browser.force_login(owner.user)

    assert browser.send("delete", _detail_url(account)).status_code == 204
    assert browser.send("delete", _detail_url(account)).status_code == 204
    account.refresh_from_db()
    assert account.status == PaymentAccount.Status.DISABLED
    assert AuditLog.objects.for_org(org).filter(action="payment_account.disable").count() == 1


@pytest.mark.parametrize(
    ("secret", "hint"),
    [
        ("sk_live_" + "x" * 30 + "a1b2", "sk_live_…a1b2"),
        ("sk_test_" + "x" * 30 + "9z9z", "sk_test_…9z9z"),
        ("daraja-consumer-secret-abcd", "…abcd"),  # no known prefix: nothing but the tail
    ],
)
def test_secret_hint(secret, hint):
    assert secret_hint(secret) == hint


# Encryption and key rotation


def test_encrypt_decrypt_round_trip():
    ciphertext = crypto.encrypt(SECRET)

    assert isinstance(ciphertext, bytes)
    assert SECRET.encode() not in ciphertext
    assert crypto.decrypt(ciphertext) == SECRET
    assert crypto.encrypt(SECRET) != ciphertext  # Fernet tokens are randomised


def test_missing_or_bad_keys_are_a_configuration_error(settings):
    settings.NOVA_FERNET_KEYS = []
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt(SECRET)
    settings.NOVA_FERNET_KEYS = ["not-a-fernet-key"]
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt(SECRET)


def test_decryption_error_reveals_nothing(settings):
    ciphertext = crypto.encrypt(SECRET)
    settings.NOVA_FERNET_KEYS = [Fernet.generate_key().decode()]

    with pytest.raises(crypto.DecryptionError) as exc_info:
        crypto.decrypt(ciphertext)

    assert SECRET not in str(exc_info.value)
    assert ciphertext.decode() not in str(exc_info.value)
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__


def test_rotation_command_reencrypts_every_row_with_the_newest_key(settings, caplog):
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.NOVA_FERNET_KEYS = [old_key]
    accounts = [PaymentAccountFactory(secret_key=f"sk_live_{i}" + "q" * 30) for i in range(3)]

    settings.NOVA_FERNET_KEYS = [new_key, old_key]
    with caplog.at_level(logging.INFO, logger="payments"):
        call_command("rotate_payment_secrets", stdout=io.StringIO())

    assert "re-encrypted 3 payment secret(s)" in caplog.text
    settings.NOVA_FERNET_KEYS = [new_key]  # the old key can now be dropped
    for i, account in enumerate(accounts):
        account.refresh_from_db()
        ciphertext = bytes(account.secret_key_encrypted)
        assert Fernet(new_key.encode()).decrypt(ciphertext).decode() == f"sk_live_{i}" + "q" * 30
        assert crypto.decrypt(ciphertext) == f"sk_live_{i}" + "q" * 30
    settings.NOVA_FERNET_KEYS = [old_key]
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(accounts[0].secret_key_encrypted)


def test_rotation_command_changes_nothing_if_a_row_cannot_be_decrypted(settings):
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.NOVA_FERNET_KEYS = [old_key]
    account = PaymentAccountFactory()
    before = bytes(account.secret_key_encrypted)

    settings.NOVA_FERNET_KEYS = [new_key]  # forgot to keep the old key
    with pytest.raises(CommandError) as exc_info:
        call_command("rotate_payment_secrets")

    assert str(account.id) in str(exc_info.value)
    account.refresh_from_db()
    assert bytes(account.secret_key_encrypted) == before
