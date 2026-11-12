from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from core.api.serializers import DeliverySiteSerializer
from core.delivery.base import DeliveryAPIView


class SiteView(DeliveryAPIView):
    @extend_schema(operation_id="delivery_site_retrieve", responses=DeliverySiteSerializer)
    def get(self, request: Request) -> Response:
        return Response(DeliverySiteSerializer(self.site).data)
