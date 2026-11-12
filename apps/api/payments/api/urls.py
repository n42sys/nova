from django.urls import path

from payments.api import views

urlpatterns = [
    path("", views.PaymentAccountListView.as_view(), name="payment-account-list"),
    path(
        "<uuid:account_id>/",
        views.PaymentAccountDetailView.as_view(),
        name="payment-account-detail",
    ),
    path(
        "<uuid:account_id>/verify/",
        views.PaymentAccountVerifyView.as_view(),
        name="payment-account-verify",
    ),
]
