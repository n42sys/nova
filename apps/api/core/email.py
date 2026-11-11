from functools import partial

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.mail.backends.base import BaseEmailBackend
from django.db import transaction

from core.tasks import send_email


class ResendCeleryEmailBackend(BaseEmailBackend):
    """Prod email backend: queue each message for Resend delivery after the transaction commits."""

    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        for message in email_messages:
            transaction.on_commit(partial(send_email.delay, self._payload(message)))
        return len(email_messages)

    @staticmethod
    def _payload(message: EmailMessage) -> dict:
        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
            "text": message.body,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)
        if isinstance(message, EmailMultiAlternatives):
            for content, mimetype in message.alternatives:
                if mimetype == "text/html":
                    payload["html"] = content
        return payload
