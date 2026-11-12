from rest_framework import serializers

from core.models import SITE_ROLE_CHOICES, Invitation, Organization, Role, Site


class SiteRoleSummarySerializer(serializers.Serializer):
    site_id = serializers.UUIDField(source="site.id")
    site_slug = serializers.CharField(source="site.slug")
    site_name = serializers.CharField(source="site.name")
    role = serializers.ChoiceField(choices=SITE_ROLE_CHOICES)


class MeOrganizationSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="organization.id")
    slug = serializers.CharField(source="organization.slug")
    name = serializers.CharField(source="organization.name")
    status = serializers.ChoiceField(
        source="organization.status", choices=Organization.Status.choices
    )
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True)
    site_roles = SiteRoleSummarySerializer(many=True)


class MeSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="user.id")
    email = serializers.EmailField(source="user.email")
    name = serializers.CharField(source="user.name")
    organizations = MeOrganizationSerializer(source="memberships", many=True)


class OrganizationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.CharField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=Organization.Status.choices)
    features = serializers.DictField()


class OrganizationUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)


class SiteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    domain = serializers.CharField(allow_null=True)
    timezone = serializers.CharField()
    default_locale = serializers.CharField()
    settings = serializers.DictField()
    status = serializers.ChoiceField(choices=Site.Status.choices)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class SiteWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=63)
    timezone = serializers.CharField(max_length=64, required=False)
    default_locale = serializers.CharField(max_length=16, required=False)
    settings = serializers.DictField(required=False)


class UserSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    name = serializers.CharField()


class MemberSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    user = UserSummarySerializer()
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True)
    site_roles = SiteRoleSummarySerializer(many=True)
    created_at = serializers.DateTimeField()


class MemberUpdateSerializer(serializers.Serializer):
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True)


class SiteRoleWriteSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=SITE_ROLE_CHOICES)


class AuditLogQuerySerializer(serializers.Serializer):
    cursor = serializers.CharField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=50)


class AuditLogEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    action = serializers.CharField()
    actor_user = UserSummarySerializer(allow_null=True)
    actor_token_id = serializers.UUIDField(allow_null=True)
    target_type = serializers.CharField()
    target_id = serializers.CharField()
    metadata = serializers.DictField()
    ip = serializers.IPAddressField(allow_null=True)
    created_at = serializers.DateTimeField()


class AuditLogPageSerializer(serializers.Serializer):
    results = AuditLogEntrySerializer(many=True, source="items")
    next_cursor = serializers.CharField(allow_null=True)


class InvitationSiteRoleSerializer(serializers.Serializer):
    site_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=SITE_ROLE_CHOICES)


class InvitationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True)
    site_roles = InvitationSiteRoleSerializer(many=True)
    status = serializers.ChoiceField(choices=Invitation.Status.choices)
    invited_by = UserSummarySerializer(allow_null=True)
    expires_at = serializers.DateTimeField()
    accepted_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True, required=False)
    site_roles = InvitationSiteRoleSerializer(many=True, required=False)


class InvitationPreviewOrganizationSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()


class InvitationPreviewSiteRoleSerializer(serializers.Serializer):
    site_id = serializers.UUIDField()
    site_name = serializers.CharField()
    role = serializers.ChoiceField(choices=SITE_ROLE_CHOICES)


class InvitationPreviewSerializer(serializers.Serializer):
    organization = InvitationPreviewOrganizationSerializer()
    email = serializers.EmailField()
    invited_by_name = serializers.CharField(allow_null=True)
    org_role = serializers.ChoiceField(choices=Role.choices, allow_null=True)
    site_roles = InvitationPreviewSiteRoleSerializer(many=True)
    expires_at = serializers.DateTimeField()
    account_exists = serializers.BooleanField()
