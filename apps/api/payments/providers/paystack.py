"""Paystack (https://paystack.com/docs/api/).

verify_credentials calls GET /integration/payment_session_timeout: a read-only endpoint that
requires the secret key (Bearer) and returns a single integer, so a successful call proves
the key works without fetching balances, customers or transactions.
"""

import logging

import httpx
from django.conf import settings

from core import crypto
from core.exceptions import ProviderUnavailable
from payments.models import PaymentAccount
from payments.providers.base import CredentialsRejected

logger = logging.getLogger(__name__)

VERIFY_PATH = "/integration/payment_session_timeout"
TIMEOUT_SECONDS = 10.0


class PaystackProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport  # tests pass an httpx.MockTransport

    def verify_credentials(self, account: PaymentAccount) -> None:
        """401/403: keys refused. Unreachable, 429 or 5xx: ProviderUnavailable (503).

        Messages and logs carry the status code only, never the key or response body.
        """
        secret = crypto.decrypt(account.secret_key_encrypted)
        try:
            with httpx.Client(
                base_url=settings.PAYSTACK_API_BASE_URL,
                timeout=TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                response = client.get(
                    VERIFY_PATH,
                    headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "Paystack unreachable verifying account %s: %s", account.id, type(exc).__name__
            )
            raise ProviderUnavailable("Paystack could not be reached. Try again shortly.") from None

        if response.status_code in (401, 403):
            logger.info(
                "Paystack refused keys for account %s (%s)", account.id, response.status_code
            )
            raise CredentialsRejected(f"Paystack answered {response.status_code}")
        if response.status_code == 200 and _is_success(response):
            return
        logger.warning(
            "Unexpected Paystack answer verifying account %s: %s", account.id, response.status_code
        )
        raise ProviderUnavailable("Paystack did not answer as expected. Try again shortly.")


def _is_success(response: httpx.Response) -> bool:
    try:
        return response.json().get("status") is True
    except ValueError:
        return False
