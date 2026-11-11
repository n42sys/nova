"""Test-only URLconf: the real routes plus a probe view built on OrgScopedAPIView."""

from django.urls import include, path
from rest_framework.response import Response

from core.api.base import OrgScopedAPIView


class ProbeView(OrgScopedAPIView):
    def get(self, request, org):
        return Response(
            {
                "org": self.ctx.organization.slug,
                "org_role": self.ctx.membership.org_role,
                "ip": self.ctx.ip,
                "actor_type": self.ctx.actor_type,
            }
        )

    def post(self, request, org):
        return Response({"ok": True})


urlpatterns = [
    path("", include("nova.urls")),
    path("api/manage/orgs/<slug:org>/probe/", ProbeView.as_view()),
]
