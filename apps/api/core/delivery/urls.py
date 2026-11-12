from django.urls import path

from core.delivery.views import SiteView

urlpatterns = [
    path("site/", SiteView.as_view(), name="delivery-site"),
]
