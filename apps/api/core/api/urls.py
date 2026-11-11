from django.urls import path

from core.api.views import MeView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
]
