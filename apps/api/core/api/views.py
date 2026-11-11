from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.base import OrgScopedAPIView
from core.api.serializers import (
    AuditLogPageSerializer,
    AuditLogQuerySerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    MeSerializer,
    OrganizationSerializer,
    OrganizationUpdateSerializer,
    SiteRoleWriteSerializer,
    SiteSerializer,
    SiteWriteSerializer,
)
from core.auth import SessionAuthentication
from core.exceptions import NotFound
from core.models import Membership, Role, Site
from core.selectors.memberships import get_member, list_memberships_for_user
from core.selectors.sites import get_site, get_visible_site, list_sites
from core.services.audit import view_audit_log
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
        return Response(SiteSerializer(sites, many=True).data)

    @extend_schema(
        operation_id="sites_create", request=SiteWriteSerializer, responses={201: SiteSerializer}
    )
    def post(self, request: Request, org: str) -> Response:
        data = SiteWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        site = create_site(self.ctx, **data.validated_data)
        return Response(SiteSerializer(site).data, status=status.HTTP_201_CREATED)


class SiteDetailView(OrgScopedAPIView):
    def get_site(self, site_id) -> Site:
        site = get_visible_site(self.ctx.organization, site_id, membership=self.ctx.membership)
        if site is None:
            raise NotFound()
        return site

    @extend_schema(operation_id="sites_retrieve", responses=SiteSerializer)
    def get(self, request: Request, org: str, site_id) -> Response:
        return Response(SiteSerializer(self.get_site(site_id)).data)

    @extend_schema(
        operation_id="sites_update",
        request=SiteWriteSerializer(partial=True),
        responses=SiteSerializer,
    )
    def patch(self, request: Request, org: str, site_id) -> Response:
        site = self.get_site(site_id)
        data = SiteWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(SiteSerializer(update_site(self.ctx, site, **data.validated_data)).data)

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
