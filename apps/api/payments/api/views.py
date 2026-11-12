from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.api.base import OrgScopedAPIView
from core.exceptions import NotFound
from payments.api.serializers import (
    PaymentAccountCreateSerializer,
    PaymentAccountKeysSerializer,
    PaymentAccountSerializer,
)
from payments.models import PaymentAccount
from payments.selectors import get_payment_account
from payments.services import (
    create_payment_account,
    disable_payment_account,
    replace_payment_account_keys,
    verify_payment_account,
    view_payment_accounts,
)


class PaymentAccountLookupMixin:
    def get_account(self, account_id) -> PaymentAccount:
        account = get_payment_account(self.ctx.organization, account_id)
        if account is None:
            raise NotFound()
        return account


class PaymentAccountListView(OrgScopedAPIView):
    @extend_schema(
        operation_id="payment_accounts_list", responses=PaymentAccountSerializer(many=True)
    )
    def get(self, request: Request, org: str) -> Response:
        return Response(PaymentAccountSerializer(view_payment_accounts(self.ctx), many=True).data)

    @extend_schema(
        operation_id="payment_accounts_create",
        request=PaymentAccountCreateSerializer,
        responses={201: PaymentAccountSerializer},
    )
    def post(self, request: Request, org: str) -> Response:
        data = PaymentAccountCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        account = create_payment_account(self.ctx, **data.validated_data)
        return Response(PaymentAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class PaymentAccountDetailView(PaymentAccountLookupMixin, OrgScopedAPIView):
    @extend_schema(
        operation_id="payment_accounts_replace_keys",
        request=PaymentAccountKeysSerializer,
        responses=PaymentAccountSerializer,
    )
    def patch(self, request: Request, org: str, account_id) -> Response:
        account = self.get_account(account_id)
        data = PaymentAccountKeysSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        account = replace_payment_account_keys(self.ctx, account, **data.validated_data)
        return Response(PaymentAccountSerializer(account).data)

    @extend_schema(operation_id="payment_accounts_disable", responses={204: None})
    def delete(self, request: Request, org: str, account_id) -> Response:
        disable_payment_account(self.ctx, self.get_account(account_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentAccountVerifyView(PaymentAccountLookupMixin, OrgScopedAPIView):
    @extend_schema(
        operation_id="payment_accounts_verify", request=None, responses=PaymentAccountSerializer
    )
    def post(self, request: Request, org: str, account_id) -> Response:
        account = verify_payment_account(self.ctx, self.get_account(account_id))
        return Response(PaymentAccountSerializer(account).data)
