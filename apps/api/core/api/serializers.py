from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import storage
from core.models import (
    SITE_ROLE_CHOICES,
    ApiToken,
    Invitation,
    MediaAsset,
    Organization,
    Role,
    Site,
)
from core.permissions import Perm, member_permissions

PERM_CHOICES = [(perm.value, perm.value) for perm in Perm]


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
    permissions = serializers.SerializerMethodField(
        help_text="Perms from the org role (org-wide). Per-site perms come with each site."
    )

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=PERM_CHOICES)))
    def get_permissions(self, membership) -> list[str]:
        return member_permissions(membership)


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
    permissions = serializers.SerializerMethodField(
        help_text="The caller's perms on this site (needs `membership` in the context)."
    )

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=PERM_CHOICES)))
    def get_permissions(self, site) -> list[str]:
        return member_permissions(self.context.get("membership"), site)


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


class ApiTokenSerializer(serializers.Serializer):
    """Never includes the secret or its hash."""

    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=ApiToken.Kind.choices)
    prefix = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_used_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)


class ApiTokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(choices=ApiToken.Kind.choices)


class ApiTokenCreatedSerializer(ApiTokenSerializer):
    token = serializers.CharField(help_text="The full token. Shown only once; store it now.")


class DeliverySiteSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    timezone = serializers.CharField()
    locale = serializers.CharField(source="default_locale")


class MediaUploadRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    mime_type = serializers.CharField(max_length=100)
    size_bytes = serializers.IntegerField(min_value=1)
    site_id = serializers.UUIDField(required=False, allow_null=True)


class MediaUploadSerializer(serializers.Serializer):
    asset_id = serializers.UUIDField(source="asset.id")
    file_key = serializers.CharField(source="asset.file_key")
    upload_url = serializers.URLField()
    method = serializers.CharField(default="PUT")
    headers = serializers.DictField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()


class MediaConfirmSerializer(serializers.Serializer):
    asset_id = serializers.UUIDField()
    alt_text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class MediaAssetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField(allow_null=True)
    file_key = serializers.CharField()
    url = serializers.SerializerMethodField()
    mime_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    width = serializers.IntegerField(allow_null=True)
    height = serializers.IntegerField(allow_null=True)
    alt_text = serializers.CharField()
    status = serializers.ChoiceField(choices=MediaAsset.Status.choices)
    uploaded_by = UserSummarySerializer(allow_null=True)
    created_at = serializers.DateTimeField()

    def get_url(self, asset: MediaAsset) -> str | None:
        return storage.public_url(asset.file_key)


class MediaUpdateSerializer(serializers.Serializer):
    alt_text = serializers.CharField(max_length=500, allow_blank=True)


class MediaQuerySerializer(serializers.Serializer):
    site_id = serializers.UUIDField(required=False)
    mime_prefix = serializers.CharField(required=False, max_length=100)
    cursor = serializers.CharField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=50)


class MediaPageSerializer(serializers.Serializer):
    results = MediaAssetSerializer(many=True, source="items")
    next_cursor = serializers.CharField(allow_null=True)
