from rest_framework import serializers

from core.models import Organization, Role


class MeSiteRoleSerializer(serializers.Serializer):
    site_id = serializers.UUIDField(source="site.id")
    site_slug = serializers.CharField(source="site.slug")
    site_name = serializers.CharField(source="site.name")
    role = serializers.ChoiceField(choices=Role.choices)


class MeOrganizationSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="organization.id")
    slug = serializers.CharField(source="organization.slug")
    name = serializers.CharField(source="organization.name")
    status = serializers.ChoiceField(
        source="organization.status", choices=Organization.Status.choices
    )
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True)
    site_roles = MeSiteRoleSerializer(many=True)


class MeSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="user.id")
    email = serializers.EmailField(source="user.email")
    name = serializers.CharField(source="user.name")
    organizations = MeOrganizationSerializer(source="memberships", many=True)
