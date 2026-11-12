from rest_framework.request import Request
from rest_framework.views import APIView

from core.auth import ApiTokenAuthentication, ApiTokenRateThrottle, HasApiToken
from core.context import ActorType, RequestContext
from core.models import ApiToken, Organization, Site
from core.request import get_client_ip


class DeliveryAPIView(APIView):
    """Base for every `/api/v1/…` view: bearer API token only, never a session.

    Exposes the token's `self.site` and `self.organization`, and `self.ctx` (actor TOKEN).
    Delivery views must read only from `self.site`; a token never sees another site.
    """

    authentication_classes = [ApiTokenAuthentication]
    permission_classes = [HasApiToken]
    throttle_classes = [ApiTokenRateThrottle]

    api_token: ApiToken
    site: Site
    organization: Organization
    ctx: RequestContext

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        self.api_token = request.auth
        self.site = self.api_token.site
        self.organization = self.api_token.organization
        self.ctx = RequestContext(
            user=None,
            membership=None,
            organization=self.organization,
            ip=get_client_ip(request),
            actor_type=ActorType.TOKEN,
            api_token_id=self.api_token.id,
        )
