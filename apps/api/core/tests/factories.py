import factory

from core.models import AuditLog, Membership, Organization, Role, Site, SiteRole, User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Faker("name")
    password = factory.django.Password("password")


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Organization {n}")
    slug = factory.Sequence(lambda n: f"org-{n}")


class TenantFactory(factory.django.DjangoModelFactory):
    """Base for TenantModel factories: `objects` refuses unscoped writes, so save via `unscoped`."""

    class Meta:
        abstract = True

    @classmethod
    def _get_manager(cls, model_class):
        return model_class.unscoped


class SiteFactory(TenantFactory):
    class Meta:
        model = Site

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Site {n}")
    slug = factory.Sequence(lambda n: f"site-{n}")


class MembershipFactory(TenantFactory):
    class Meta:
        model = Membership

    organization = factory.SubFactory(OrganizationFactory)
    user = factory.SubFactory(UserFactory)
    org_role = Role.EDITOR


class SiteRoleFactory(TenantFactory):
    class Meta:
        model = SiteRole

    membership = factory.SubFactory(MembershipFactory)
    organization = factory.SelfAttribute("membership.organization")
    site = factory.SubFactory(SiteFactory, organization=factory.SelfAttribute("..organization"))
    role = Role.EDITOR


class AuditLogFactory(TenantFactory):
    class Meta:
        model = AuditLog

    organization = factory.SubFactory(OrganizationFactory)
    action = "test.action"
