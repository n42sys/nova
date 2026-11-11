import pytest
from django.db import IntegrityError, connection

from core.models import Site
from core.tests.factories import OrganizationFactory, SiteFactory

pytestmark = pytest.mark.django_db


def test_defaults():
    site = SiteFactory()

    assert site.timezone == "Africa/Nairobi"
    assert site.default_locale == "en"
    assert site.settings == {}
    assert site.status == Site.Status.ACTIVE
    assert site.domain is None


def test_slug_is_unique_per_org():
    site = SiteFactory(slug="main")

    with pytest.raises(IntegrityError):
        SiteFactory(organization=site.organization, slug="main")


def test_same_slug_allowed_in_another_org():
    SiteFactory(slug="main")
    SiteFactory(slug="main", organization=OrganizationFactory())


def test_domain_is_globally_unique():
    SiteFactory(domain="culture.example")

    with pytest.raises(IntegrityError):
        SiteFactory(domain="culture.example")


def test_many_sites_without_domain_allowed():
    org = OrganizationFactory()
    SiteFactory(organization=org)
    SiteFactory(organization=org)


def test_domain_is_stored_lowercase():
    site = SiteFactory(domain="Culture.Example")

    assert site.domain == "culture.example"
    site.refresh_from_db()
    assert site.domain == "culture.example"


def test_domain_differing_only_in_case_clashes():
    SiteFactory(domain="Culture.example")

    with pytest.raises(IntegrityError):
        SiteFactory(domain="culture.example")


def test_domain_lookup_is_case_insensitive():
    site = SiteFactory(domain="culture.example")

    assert Site.objects.for_org(site.organization).get(domain="Culture.Example") == site


def test_case_insensitive_domain_constraint_covers_raw_sql():
    site = SiteFactory(domain="culture.example")
    other = SiteFactory(organization=site.organization)

    with pytest.raises(IntegrityError), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE core_site SET domain = %s WHERE id = %s", ["Culture.Example", other.id]
        )
