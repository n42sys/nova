from payments.models import PaymentAccount
from payments.providers.base import PaymentProvider
from payments.providers.paystack import PaystackProvider

# Provider name -> implementation. A provider missing here cannot be verified.
PROVIDERS: dict[str, PaymentProvider] = {
    PaymentAccount.Provider.PAYSTACK: PaystackProvider(),
}


def get_provider(name: str) -> PaymentProvider | None:
    return PROVIDERS.get(PaymentAccount.Provider(name))
