from typing import Any

import resend
from celery import shared_task
from django.conf import settings


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def send_email(payload: dict[str, Any]) -> None:
    """Deliver one email through Resend. Payload is built by ResendCeleryEmailBackend."""
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(payload)
