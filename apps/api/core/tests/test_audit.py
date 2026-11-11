import uuid
from datetime import UTC, datetime
from unittest import mock

import pytest
from django.db.models import ProtectedError

from core.audit import audit
from core.context import ActorType, RequestContext
from core.exceptions import ValidationFailed
from core.models import AppendOnlyError, AuditLog
from core.selectors.audit import list_audit_log
from core.tests.factories import (
    AuditLogFactory,
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx():
    membership = MembershipFactory()
    return RequestContext(
        user=membership.user,
        membership=membership,
        organization=membership.organization,
        ip="203.0.113.7",
        actor_type=ActorType.USER,
    )


# Writing


def test_audit_records_actor_target_and_ip(ctx):
    site = SiteFactory(organization=ctx.organization)

    entry = audit(ctx, "site.create", site, {"name": site.name, "site_id": site.id})

    entry = AuditLog.objects.for_org(ctx.organization).get(id=entry.id)
    assert entry.organization == ctx.organization
    assert entry.actor_user == ctx.user
    assert entry.actor_token_id is None
    assert entry.action == "site.create"
    assert entry.target_type == "core.site"
    assert entry.target_id == str(site.id)
    assert entry.metadata == {"name": site.name, "site_id": str(site.id)}
    assert entry.ip == "203.0.113.7"
    assert entry.id.version == 7


def test_audit_without_target_or_metadata(ctx):
    entry = audit(ctx, "org.export", None)

    assert (entry.target_type, entry.target_id, entry.metadata) == ("", "", {})


def test_system_actor_has_no_user(ctx):
    system_ctx = RequestContext(
        user=None,
        membership=None,
        organization=ctx.organization,
        ip=None,
        actor_type=ActorType.SYSTEM,
    )

    assert audit(system_ctx, "org.bootstrap", None).actor_user is None


def test_sensitive_metadata_keys_are_stripped(ctx):
    entry = audit(
        ctx,
        "payments.account.update",
        None,
        {
            "provider": "paystack",
            "secret_key": "sk_live_abc",
            "SecretKey": "sk_live_abc",
            "token": "nova_dlv_x_y",
            "api_token_raw": "nova_dlv_x_y",
            "password": "hunter2",
            "new_Password": "hunter2",
            "nested": {"client_secret": "s", "keep": 1, "deeper": [{"refresh_token": "t"}]},
        },
    )

    entry = AuditLog.objects.for_org(ctx.organization).get(id=entry.id)
    assert entry.metadata == {
        "provider": "paystack",
        "nested": {"keep": 1, "deeper": [{}]},
    }
    for raw in ("sk_live_abc", "nova_dlv_x_y", "hunter2"):
        assert raw not in str(entry.metadata)


def test_audit_does_not_mutate_callers_metadata(ctx):
    metadata = {"password": "hunter2", "name": "x"}

    audit(ctx, "user.update", None, metadata)

    assert metadata == {"password": "hunter2", "name": "x"}


# Append-only


def test_updating_an_entry_via_save_raises():
    entry = AuditLogFactory()
    entry.action = "tampered"

    with pytest.raises(AppendOnlyError):
        entry.save()


def test_queryset_update_raises():
    entry = AuditLogFactory()

    with pytest.raises(AppendOnlyError):
        AuditLog.objects.for_org(entry.organization).update(action="tampered")
    with pytest.raises(AppendOnlyError):
        AuditLog.unscoped.filter(id=entry.id).update(action="tampered")


def test_bulk_update_raises():
    entry = AuditLogFactory()
    entry.action = "tampered"

    with pytest.raises(AppendOnlyError):
        AuditLog.unscoped.bulk_update([entry], ["action"])


def test_instance_delete_raises():
    entry = AuditLogFactory()

    with pytest.raises(AppendOnlyError):
        entry.delete()


def test_queryset_delete_raises():
    entry = AuditLogFactory()

    with pytest.raises(AppendOnlyError):
        AuditLog.objects.for_org(entry.organization).delete()
    with pytest.raises(AppendOnlyError):
        AuditLog.unscoped.filter(id=entry.id).delete()


def test_entries_are_unchanged_after_refused_writes():
    entry = AuditLogFactory(action="original")

    with pytest.raises(AppendOnlyError):
        AuditLog.unscoped.filter(id=entry.id).update(action="tampered")

    assert AuditLog.unscoped.get(id=entry.id).action == "original"


def test_objects_manager_is_still_guarded():
    with pytest.raises(Exception, match="for_org"):
        AuditLog.objects.all()


# Selector


def test_list_is_newest_first_and_scoped_to_org(ctx):
    first = audit(ctx, "a", None)
    second = audit(ctx, "b", None)
    other_org_ctx = RequestContext(
        user=None,
        membership=None,
        organization=OrganizationFactory(),
        ip=None,
        actor_type=ActorType.SYSTEM,
    )
    audit(other_org_ctx, "other", None)

    page = list_audit_log(ctx.organization)

    assert page.items == [second, first]
    assert page.next_cursor is None


def test_cursor_walks_every_entry_once(ctx):
    entries = [audit(ctx, f"action.{i}", None) for i in range(7)]

    seen, cursor = [], None
    while True:
        page = list_audit_log(ctx.organization, cursor=cursor, limit=3)
        seen.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == list(reversed(entries))


def test_cursor_breaks_ties_on_id(ctx):
    frozen = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    with mock.patch("django.utils.timezone.now", return_value=frozen):
        entries = [audit(ctx, f"same.{i}", None) for i in range(5)]
    assert {entry.created_at for entry in entries} == {frozen}

    first = list_audit_log(ctx.organization, limit=2)
    second = list_audit_log(ctx.organization, cursor=first.next_cursor, limit=2)
    third = list_audit_log(ctx.organization, cursor=second.next_cursor, limit=2)

    seen = first.items + second.items + third.items
    assert seen == sorted(entries, key=lambda entry: entry.id, reverse=True)
    assert third.next_cursor is None


def test_limit_is_clamped(ctx):
    for i in range(3):
        audit(ctx, f"a.{i}", None)

    assert len(list_audit_log(ctx.organization, limit=0).items) == 1
    assert len(list_audit_log(ctx.organization, limit=10_000).items) == 3


@pytest.mark.parametrize(
    "cursor",
    ["not-base64!", "Zm9v", "MjAyNi0xMS0xMVQxMjowMDowMHxub3QtYS11dWlk", str(uuid.uuid4())],
)
def test_invalid_cursor_is_a_validation_error(ctx, cursor):
    with pytest.raises(ValidationFailed):
        list_audit_log(ctx.organization, cursor=cursor)


def test_deleting_a_user_or_org_with_audit_history_is_blocked(ctx):
    entry = audit(ctx, "site.create", None)

    with pytest.raises(ProtectedError):
        ctx.user.delete()
    with pytest.raises(ProtectedError):
        ctx.organization.delete()

    entry = AuditLog.objects.for_org(ctx.organization).get(id=entry.id)
    assert entry.actor_user_id == ctx.user.id
