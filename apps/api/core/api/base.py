from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.views import APIView

from core.auth import SessionAuthentication
from core.context import ActorType, RequestContext
from core.exceptions import NotFound
from core.request import get_client_ip
from core.selectors.memberships import get_membership
from core.selectors.organizations import get_active_organization


class OrgScopedAPIView(APIView):
    """Base for every `/api/manage/orgs/{org}/…` view.

    Session auth only. After DRF authenticates the request (401 if anonymous), resolves the
    `{org}` slug and the caller's membership, with site roles prefetched, and builds
    `self.ctx` once for the request. Unknown org, suspended org and non-member all raise the
    same NotFound, so tenants cannot probe for each other. `is_staff` grants nothing here.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    org_url_kwarg = "org"

    ctx: RequestContext

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        self.ctx = self.build_context(request, kwargs[self.org_url_kwarg])

    def serializer_context(self) -> dict:
        """Context for serializers that report the caller's permissions."""
        return {"membership": self.ctx.membership}

    @staticmethod
    def build_context(request: Request, org_slug: str) -> RequestContext:
        organization = get_active_organization(org_slug)
        membership = get_membership(organization, request.user) if organization else None
        if membership is None:
            raise NotFound()
        return RequestContext(
            user=request.user,
            membership=membership,
            organization=organization,
            ip=get_client_ip(request),
            actor_type=ActorType.USER,
        )
