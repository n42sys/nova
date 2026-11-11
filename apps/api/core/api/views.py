from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.serializers import MeSerializer
from core.auth import SessionAuthentication
from core.selectors.memberships import list_memberships_for_user


class MeView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="me_retrieve", responses=MeSerializer)
    def get(self, request: Request) -> Response:
        memberships = list_memberships_for_user(request.user)
        return Response(MeSerializer({"user": request.user, "memberships": memberships}).data)
