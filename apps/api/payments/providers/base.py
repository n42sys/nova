from typing import Protocol

from payments.models import PaymentAccount


class CredentialsRejected(Exception):
    """The provider says the account's keys are not valid."""


class PaymentProvider(Protocol):
    """What Nova needs from a payment provider. Checkout methods arrive in Phase 4.

    Implementations must never put a secret key in an exception message or log line.
    """

    def verify_credentials(self, account: PaymentAccount) -> None:
        """Make one authenticated, read-only call. Raise CredentialsRejected if the keys
        are refused, or core.exceptions.ProviderUnavailable (503) if the provider cannot be
        reached or fails; return None if the keys work."""
        ...
