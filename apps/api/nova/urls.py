from django.urls import include, path

urlpatterns = [
    path("_allauth/", include("allauth.headless.urls")),
    path("api/manage/", include("core.api.urls")),
    path("api/manage/orgs/<slug:org>/payment-accounts/", include("payments.api.urls")),
    path("api/v1/", include("core.delivery.urls")),
]
