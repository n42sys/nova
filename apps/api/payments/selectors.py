import uuid

from core.models import Organization
from payments.models import PaymentAccount


def list_payment_accounts(org: Organization) -> list[PaymentAccount]:
    return list(PaymentAccount.objects.for_org(org).order_by("provider"))


def get_payment_account(org: Organization, account_id: uuid.UUID) -> PaymentAccount | None:
    return PaymentAccount.objects.for_org(org).filter(id=account_id).first()
