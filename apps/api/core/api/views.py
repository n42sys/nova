from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.base import OrgScopedAPIView
from core.api.serializers import (
    ApiTokenCreatedSerializer,
    ApiTokenCreateSerializer,
    ApiTokenSerializer,
    AuditLogPageSerializer,
    AuditLogQuerySerializer,
    InvitationCreateSerializer,
    InvitationPreviewSerializer,
    InvitationSerializer,
    MediaAssetSerializer,
    MediaConfirmSerializer,
    MediaPageSerializer,
    MediaQuerySerializer,
    MediaUpdateSerializer,
    MediaUploadRequestSerializer,
    MediaUploadSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    MeOrganizationSerializer,
    MeSerializer,
    OrganizationSerializer,
    OrganizationUpdateSerializer,
    SiteRoleWriteSerializer,
    SiteSerializer,
    SiteWriteSerializer,
)
from core.auth import SessionAuthentication, enforce_csrf
from core.exceptions import Gone, NotFound
from core.invitation_session import forget_invitation, remember_invitation
from core.models import ApiToken, Invitation, MediaAsset, Membership, Role, Site
from core.request import get_client_ip
from core.selectors.api_tokens import get_api_token
from core.selectors.invitations import (
    get_invitation,
    invitation_preview,
)
from core.selectors.media import get_media
from core.selectors.memberships import get_member, list_memberships_for_user
from core.selectors.sites import get_site, get_visible_site, list_sites
from core.selectors.token_resolution import resolve_invitation_token
from core.services.api_tokens import create_api_token, revoke_api_token, view_api_tokens
from core.services.audit import view_audit_log
from core.services.invitations import (
    accept_invitation,
    invite_member,
    resend_invitation,
    revoke_invitation,
    view_invitations,
)
from core.services.media import (
    confirm_upload,
    delete_media,
    request_upload,
    update_media,
    view_media,
)
from core.services.memberships import (
    change_org_role,
    remove_member,
    remove_site_role,
    set_site_role,
    view_members,
)
from core.services.organizations import update_organization
from core.services.sites import archive_site, create_site, update_site


class MeView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="me_retrieve", responses=MeSerializer)
    def get(self, request: Request) -> Response:
        memberships = list_memberships_for_user(request.user)
        return Response(MeSerializer({"user": request.user, "memberships": memberships}).data)


class OrgDetailView(OrgScopedAPIView):
    @extend_schema(operation_id="org_retrieve", responses=OrganizationSerializer)
    def get(self, request: Request, org: str) -> Response:
        return Response(OrganizationSerializer(self.ctx.organization).data)

    @extend_schema(
        operation_id="org_update",
        request=OrganizationUpdateSerializer,
        responses=OrganizationSerializer,
    )
    def patch(self, request: Request, org: str) -> Response:
        data = OrganizationUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        organization = update_organization(self.ctx, **data.validated_data)
        return Response(OrganizationSerializer(organization).data)


class SiteListView(OrgScopedAPIView):
    @extend_schema(operation_id="sites_list", responses=SiteSerializer(many=True))
    def get(self, request: Request, org: str) -> Response:
        sites = list_sites(self.ctx.organization, membership=self.ctx.membership)
        return Response(SiteSerializer(sites, many=True, context=self.serializer_context()).data)

    @extend_schema(
        operation_id="sites_create", request=SiteWriteSerializer, responses={201: SiteSerializer}
    )
    def post(self, request: Request, org: str) -> Response:
        data = SiteWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        site = create_site(self.ctx, **data.validated_data)
        return Response(
            SiteSerializer(site, context=self.serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


class SiteDetailView(OrgScopedAPIView):
    def get_site(self, site_id) -> Site:
        site = get_visible_site(self.ctx.organization, site_id, membership=self.ctx.membership)
        if site is None:
            raise NotFound()
        return site

    @extend_schema(operation_id="sites_retrieve", responses=SiteSerializer)
    def get(self, request: Request, org: str, site_id) -> Response:
        return Response(
            SiteSerializer(self.get_site(site_id), context=self.serializer_context()).data
        )

    @extend_schema(
        operation_id="sites_update",
        request=SiteWriteSerializer(partial=True),
        responses=SiteSerializer,
    )
    def patch(self, request: Request, org: str, site_id) -> Response:
        site = self.get_site(site_id)
        data = SiteWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        site = update_site(self.ctx, site, **data.validated_data)
        return Response(SiteSerializer(site, context=self.serializer_context()).data)

    @extend_schema(operation_id="sites_archive", responses={204: None})
    def delete(self, request: Request, org: str, site_id) -> Response:
        archive_site(self.ctx, self.get_site(site_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberLookupMixin:
    def get_member(self, membership_id) -> Membership:
        membership = get_member(self.ctx.organization, membership_id)
        if membership is None:
            raise NotFound()
        return membership

    def member_response(self, membership: Membership) -> Response:
        return Response(MemberSerializer(self.get_member(membership.id)).data)


class MemberListView(OrgScopedAPIView):
    @extend_schema(operation_id="members_list", responses=MemberSerializer(many=True))
    def get(self, request: Request, org: str) -> Response:
        return Response(MemberSerializer(view_members(self.ctx), many=True).data)


class MemberDetailView(MemberLookupMixin, OrgScopedAPIView):
    @extend_schema(
        operation_id="members_update", request=MemberUpdateSerializer, responses=MemberSerializer
    )
    def patch(self, request: Request, org: str, membership_id) -> Response:
        membership = self.get_member(membership_id)
        data = MemberUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        org_role = data.validated_data["org_role"]
        change_org_role(self.ctx, membership, Role(org_role) if org_role else None)
        return self.member_response(membership)

    @extend_schema(operation_id="members_remove", responses={204: None})
    def delete(self, request: Request, org: str, membership_id) -> Response:
        remove_member(self.ctx, self.get_member(membership_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberSiteRoleView(MemberLookupMixin, OrgScopedAPIView):
    def get_site(self, site_id) -> Site:
        site = get_site(self.ctx.organization, site_id)
        if site is None:
            raise NotFound()
        return site

    @extend_schema(
        operation_id="members_site_role_set",
        request=SiteRoleWriteSerializer,
        responses=MemberSerializer,
    )
    def put(self, request: Request, org: str, membership_id, site_id) -> Response:
        membership = self.get_member(membership_id)
        site = self.get_site(site_id)
        data = SiteRoleWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        set_site_role(self.ctx, membership, site, Role(data.validated_data["role"]))
        return self.member_response(membership)

    @extend_schema(operation_id="members_site_role_remove", responses={204: None})
    def delete(self, request: Request, org: str, membership_id, site_id) -> Response:
        remove_site_role(self.ctx, self.get_member(membership_id), self.get_site(site_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditLogView(OrgScopedAPIView):
    @extend_schema(
        operation_id="audit_log_list",
        parameters=[AuditLogQuerySerializer],
        responses=AuditLogPageSerializer,
    )
    def get(self, request: Request, org: str) -> Response:
        query = AuditLogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = view_audit_log(self.ctx, **query.validated_data)
        return Response(AuditLogPageSerializer(page).data)


class InvitationListView(OrgScopedAPIView):
    @extend_schema(operation_id="invitations_list", responses=InvitationSerializer(many=True))
    def get(self, request: Request, org: str) -> Response:
        return Response(InvitationSerializer(view_invitations(self.ctx), many=True).data)

    @extend_schema(
        operation_id="invitations_create",
        request=InvitationCreateSerializer,
        responses={201: InvitationSerializer},
    )
    def post(self, request: Request, org: str) -> Response:
        data = InvitationCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invitation = invite_member(self.ctx, **data.validated_data)
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class InvitationLookupMixin:
    def get_invitation(self, invitation_id) -> Invitation:
        invitation = get_invitation(self.ctx.organization, invitation_id)
        if invitation is None:
            raise NotFound()
        return invitation


class InvitationDetailView(InvitationLookupMixin, OrgScopedAPIView):
    @extend_schema(operation_id="invitations_revoke", responses={204: None})
    def delete(self, request: Request, org: str, invitation_id) -> Response:
        revoke_invitation(self.ctx, self.get_invitation(invitation_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationResendView(InvitationLookupMixin, OrgScopedAPIView):
    @extend_schema(operation_id="invitations_resend", request=None, responses=InvitationSerializer)
    def post(self, request: Request, org: str, invitation_id) -> Response:
        invitation = resend_invitation(self.ctx, self.get_invitation(invitation_id))
        return Response(InvitationSerializer(invitation).data)


class InvitationTokenMixin:
    def resolve_open_invitation(self, token: str) -> Invitation:
        invitation = resolve_invitation_token(token)
        if invitation is None:
            raise NotFound()
        if invitation.status != Invitation.Status.OPEN:
            raise Gone(
                f"This invitation has {invitation.status}.", details={"status": invitation.status}
            )
        return invitation


class InvitationPreviewView(InvitationTokenMixin, APIView):
    """Public and read-only: what an invitation link offers. The token is the credential."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @extend_schema(operation_id="invitation_preview", responses=InvitationPreviewSerializer)
    def get(self, request: Request, token: str) -> Response:
        invitation = self.resolve_open_invitation(token)
        return Response(InvitationPreviewSerializer(invitation_preview(invitation)).data)


class InvitationClaimView(InvitationTokenMixin, APIView):
    """Public: remember the invitation in this session so its invitee can sign up."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @extend_schema(operation_id="invitation_claim", request=None, responses={204: None})
    def post(self, request: Request, token: str) -> Response:
        enforce_csrf(request)
        remember_invitation(request, self.resolve_open_invitation(token))
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationAcceptView(APIView):
    """Logged-in user whose email matches the invitation joins its organization.

    Status is checked by the service under a row lock, so a race cannot accept twice.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="invitation_accept", request=None, responses=MeOrganizationSerializer
    )
    def post(self, request: Request, token: str) -> Response:
        invitation = resolve_invitation_token(token)
        if invitation is None:
            raise NotFound()
        membership = accept_invitation(request.user, invitation, ip=get_client_ip(request))
        forget_invitation(request)
        membership = get_member(membership.organization, membership.id)
        return Response(MeOrganizationSerializer(membership).data)


class SiteLookupMixin:
    def get_site(self, site_id) -> Site:
        site = get_visible_site(self.ctx.organization, site_id, membership=self.ctx.membership)
        if site is None:
            raise NotFound()
        return site


class ApiTokenListView(SiteLookupMixin, OrgScopedAPIView):
    @extend_schema(operation_id="api_tokens_list", responses=ApiTokenSerializer(many=True))
    def get(self, request: Request, org: str, site_id) -> Response:
        tokens = view_api_tokens(self.ctx, self.get_site(site_id))
        return Response(ApiTokenSerializer(tokens, many=True).data)

    @extend_schema(
        operation_id="api_tokens_create",
        request=ApiTokenCreateSerializer,
        responses={201: ApiTokenCreatedSerializer},
    )
    def post(self, request: Request, org: str, site_id) -> Response:
        site = self.get_site(site_id)
        data = ApiTokenCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        created = create_api_token(
            self.ctx,
            site,
            name=data.validated_data["name"],
            kind=ApiToken.Kind(data.validated_data["kind"]),
        )
        body = {**ApiTokenSerializer(created.token).data, "token": created.raw}
        return Response(body, status=status.HTTP_201_CREATED)


class ApiTokenDetailView(SiteLookupMixin, OrgScopedAPIView):
    @extend_schema(operation_id="api_tokens_revoke", responses={204: None})
    def delete(self, request: Request, org: str, site_id, token_id) -> Response:
        site = self.get_site(site_id)
        token = get_api_token(self.ctx.organization, site, token_id)
        if token is None:
            raise NotFound()
        revoke_api_token(self.ctx, token)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MediaUploadView(SiteLookupMixin, OrgScopedAPIView):
    @extend_schema(
        operation_id="media_upload_request",
        request=MediaUploadRequestSerializer,
        responses={201: MediaUploadSerializer},
    )
    def post(self, request: Request, org: str) -> Response:
        data = MediaUploadRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        site_id = data.validated_data.pop("site_id", None)
        site = self.get_site(site_id) if site_id else None
        upload = request_upload(self.ctx, site=site, **data.validated_data)
        body = {
            "asset": upload.asset,
            "upload_url": upload.upload_url,
            "method": "PUT",
            "headers": {"Content-Type": upload.asset.mime_type},
            "expires_at": upload.expires_at,
        }
        return Response(MediaUploadSerializer(body).data, status=status.HTTP_201_CREATED)


class MediaListView(SiteLookupMixin, OrgScopedAPIView):
    @extend_schema(
        operation_id="media_list", parameters=[MediaQuerySerializer], responses=MediaPageSerializer
    )
    def get(self, request: Request, org: str) -> Response:
        query = MediaQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        site_id = query.validated_data.pop("site_id", None)
        site = self.get_site(site_id) if site_id else None
        page = view_media(self.ctx, site=site, **query.validated_data)
        return Response(MediaPageSerializer(page).data)

    @extend_schema(
        operation_id="media_confirm", request=MediaConfirmSerializer, responses=MediaAssetSerializer
    )
    def post(self, request: Request, org: str) -> Response:
        data = MediaConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        asset = get_media(
            self.ctx.organization,
            data.validated_data["asset_id"],
            statuses=(MediaAsset.Status.PENDING, MediaAsset.Status.READY),
        )
        if asset is None:
            raise NotFound()
        asset = confirm_upload(self.ctx, asset, alt_text=data.validated_data["alt_text"])
        return Response(MediaAssetSerializer(asset).data)


class MediaDetailView(OrgScopedAPIView):
    def get_asset(self, asset_id) -> MediaAsset:
        asset = get_media(self.ctx.organization, asset_id)
        if asset is None:
            raise NotFound()
        return asset

    @extend_schema(
        operation_id="media_update", request=MediaUpdateSerializer, responses=MediaAssetSerializer
    )
    def patch(self, request: Request, org: str, asset_id) -> Response:
        asset = self.get_asset(asset_id)
        data = MediaUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            MediaAssetSerializer(update_media(self.ctx, asset, **data.validated_data)).data
        )

    @extend_schema(operation_id="media_delete", responses={204: None})
    def delete(self, request: Request, org: str, asset_id) -> Response:
        delete_media(self.ctx, self.get_asset(asset_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
