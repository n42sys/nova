from django.urls import include, path

urlpatterns = [
    path("_allauth/", include("allauth.headless.urls")),
    path("api/manage/", include("core.api.urls")),
]
