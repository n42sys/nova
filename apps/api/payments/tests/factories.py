import factory

from core import crypto
from core.tests.factories import OrganizationFactory, TenantFactory
from payments.models import PaymentAccount
from payments.services import secret_hint

TEST_SECRET = "sk_test_" + "a1" * 16


class PaymentAccountFactory(TenantFactory):
    class Meta:
        model = PaymentAccount

    class Params:
        secret_key = TEST_SECRET

    organization = factory.SubFactory(OrganizationFactory)
    provider = PaymentAccount.Provider.PAYSTACK
    public_key = "pk_test_" + "b2" * 16
    secret_key_encrypted = factory.LazyAttribute(lambda o: crypto.encrypt(o.secret_key))
    secret_key_hint = factory.LazyAttribute(lambda o: secret_hint(o.secret_key))
