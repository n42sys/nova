from django.db import models

from core.models import TenantModel


class PaymentAccount(TenantModel):
    """An organization's own account with a payment provider. Nova never holds funds.

    The secret key is stored only Fernet-encrypted (core.crypto) and is never returned by
    any API; `secret_key_hint` (e.g. "sk_live_…a1b2") is what people see.
    """

    class Provider(models.TextChoices):
        PAYSTACK = "paystack", "Paystack"
        DARAJA = "daraja", "M-Pesa Daraja"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending verification"
        VERIFIED = "verified", "Verified"
        DISABLED = "disabled", "Disabled"

    provider = models.CharField(max_length=20, choices=Provider.choices)
    public_key = models.CharField(max_length=200)
    secret_key_encrypted = models.BinaryField(editable=False)
    secret_key_hint = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider"], name="payments_account_org_provider_unique"
            ),
        ]
