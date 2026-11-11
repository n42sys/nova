import pytest
from django.db import IntegrityError

from core.exceptions import NotFound, ValidationFailed
from core.models import Role, SiteRole
from core.selectors.memberships import get_membership
from core.services.memberships import _set_site_role
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


# Membership constraints


def test_membership_is_unique_per_org_and_user():
    membership = MembershipFactory()

    with pytest.raises(IntegrityError):
        MembershipFactory(organization=membership.organization, user=membership.user)


def test_user_can_belong_to_several_orgs():
    user = UserFactory()
    MembershipFactory(user=user)
    MembershipFactory(user=user)

    assert user.memberships.count() == 2


def test_org_role_may_be_null():
    assert MembershipFactory(org_role=None).org_role is None


def test_org_role_rejects_unknown_values():
    with pytest.raises(IntegrityError):
        MembershipFactory(org_role="superuser")


# SiteRole constraints


def test_site_role_is_unique_per_membership_and_site():
    site_role = SiteRoleFactory()

    with pytest.raises(IntegrityError):
        SiteRoleFactory(membership=site_role.membership, site=site_role.site)


def test_owner_cannot_be_a_site_role_in_the_database():
    with pytest.raises(IntegrityError):
        SiteRoleFactory(role=Role.OWNER)


def test_set_site_role_rejects_owner():
    membership = MembershipFactory()
    site = SiteFactory(organization=membership.organization)

    with pytest.raises(ValidationFailed):
        _set_site_role(membership=membership, site=site, role=Role.OWNER)

    assert not SiteRole.objects.for_org(membership.organization).exists()


def test_set_site_role_rejects_site_from_another_org():
    membership = MembershipFactory()
    other_site = SiteFactory(organization=OrganizationFactory())

    with pytest.raises(NotFound):
        _set_site_role(membership=membership, site=other_site, role=Role.EDITOR)

    assert not SiteRole.objects.for_org(membership.organization).exists()
    assert not SiteRole.objects.for_org(other_site.organization).exists()


def test_set_site_role_refuses_owners():
    membership = MembershipFactory(org_role=Role.OWNER)
    site = SiteFactory(organization=membership.organization)

    with pytest.raises(ValidationFailed):
        _set_site_role(membership=membership, site=site, role=Role.EDITOR)

    assert not SiteRole.objects.for_org(membership.organization).exists()


def test_set_site_role_creates_then_updates():
    membership = MembershipFactory()
    site = SiteFactory(organization=membership.organization)

    created = _set_site_role(membership=membership, site=site, role=Role.EDITOR)
    updated = _set_site_role(membership=membership, site=site, role=Role.EVENT_STAFF)

    assert created.id == updated.id
    assert created.organization_id == membership.organization_id
    assert SiteRole.objects.for_org(membership.organization).get().role == Role.EVENT_STAFF


# effective_role


def test_site_override_wins():
    site_role = SiteRoleFactory(membership__org_role=Role.ADMIN, role=Role.EVENT_STAFF)

    assert site_role.membership.effective_role(site_role.site) == Role.EVENT_STAFF


def test_owner_is_owner_on_every_site_even_with_a_site_role_row():
    # The service refuses this; the row is forced in to prove effective_role ignores it.
    site_role = SiteRoleFactory(membership__org_role=Role.OWNER, role=Role.EVENT_STAFF)
    other_site = SiteFactory(organization=site_role.organization)

    assert site_role.membership.effective_role(site_role.site) == Role.OWNER
    assert site_role.membership.effective_role(other_site) == Role.OWNER


def test_falls_back_to_org_role():
    membership = MembershipFactory(org_role=Role.ADMIN)
    site = SiteFactory(organization=membership.organization)

    assert membership.effective_role(site) == Role.ADMIN


def test_none_when_neither_exists():
    membership = MembershipFactory(org_role=None)
    site = SiteFactory(organization=membership.organization)

    assert membership.effective_role(site) is None


def test_site_role_on_one_site_does_not_apply_to_another():
    site_role = SiteRoleFactory(membership__org_role=None, role=Role.EDITOR)
    other_site = SiteFactory(organization=site_role.organization)

    assert site_role.membership.effective_role(site_role.site) == Role.EDITOR
    assert site_role.membership.effective_role(other_site) is None


def test_editor_on_one_site_and_event_staff_on_another():
    membership = MembershipFactory(org_role=None)
    main = SiteFactory(organization=membership.organization)
    events = SiteFactory(organization=membership.organization)
    _set_site_role(membership=membership, site=main, role=Role.EDITOR)
    _set_site_role(membership=membership, site=events, role=Role.EVENT_STAFF)

    assert membership.effective_role(main) == Role.EDITOR
    assert membership.effective_role(events) == Role.EVENT_STAFF


# Selector


def test_get_membership_prefetches_site_roles(django_assert_num_queries):
    membership = MembershipFactory(org_role=Role.ADMIN)
    sites = [SiteFactory(organization=membership.organization) for _ in range(3)]
    for site in sites[:2]:
        _set_site_role(membership=membership, site=site, role=Role.EDITOR)

    loaded = get_membership(membership.organization, membership.user)

    with django_assert_num_queries(0):
        roles = [loaded.effective_role(site) for site in sites]
    assert roles == [Role.EDITOR, Role.EDITOR, Role.ADMIN]


def test_get_membership_is_scoped_to_the_org():
    membership = MembershipFactory()

    assert get_membership(OrganizationFactory(), membership.user) is None
    assert get_membership(membership.organization, membership.user) == membership
