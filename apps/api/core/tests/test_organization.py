import pytest
from django.db import IntegrityError

from core.models import Organization
from core.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_defaults():
    org = OrganizationFactory()

    assert org.status == Organization.Status.ACTIVE
    assert org.features == {}
    assert org.id.version == 7


def test_slug_is_globally_unique():
    OrganizationFactory(slug="culture-interest")

    with pytest.raises(IntegrityError):
        OrganizationFactory(slug="culture-interest")
