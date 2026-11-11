import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import ProtectedError

from core.tests.factories import OrganizationFactory
from core.tests.tenant_testapp.models import Widget

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_a():
    return OrganizationFactory()


@pytest.fixture
def org_b():
    return OrganizationFactory()


@pytest.fixture
def widgets(org_a, org_b):
    return {
        "a": [Widget.unscoped.create(organization=org_a, name=f"a{i}") for i in range(2)],
        "b": [Widget.unscoped.create(organization=org_b, name="b0")],
    }


@pytest.mark.parametrize(
    "query",
    [
        lambda: Widget.objects.all(),
        lambda: Widget.objects.filter(name="a0"),
        lambda: Widget.objects.get(name="a0"),
        lambda: Widget.objects.count(),
    ],
)
def test_unscoped_queries_on_objects_raise(widgets, query):
    with pytest.raises(ImproperlyConfigured):
        query()


def test_for_org_filters_to_that_org(org_a, org_b, widgets):
    assert set(Widget.objects.for_org(org_a)) == set(widgets["a"])
    assert set(Widget.objects.for_org(org_b)) == set(widgets["b"])


def test_for_org_accepts_an_org_id(org_a, widgets):
    assert set(Widget.objects.for_org(org_a.id)) == set(widgets["a"])


def test_for_org_requires_an_org():
    with pytest.raises(ImproperlyConfigured):
        Widget.objects.for_org(None)


def test_unscoped_is_the_default_manager(widgets):
    assert Widget._meta.default_manager is Widget.unscoped
    assert Widget.unscoped.count() == 3


def test_ids_are_uuid7(widgets):
    assert widgets["a"][0].id.version == 7


def test_organization_with_rows_cannot_be_deleted(org_a, widgets):
    with pytest.raises(ProtectedError):
        org_a.delete()
